"""
2026-08-02 バックグラウンド処理3件（_save_genre_update_time / _save_audit_time /
バックグラウンド経由のrepair_finding）の接続返却安全性テスト。
minconn=0化（同日の別パッチ）により、接続がプールへ返却されないまま放置されると
物理接続がクローズされずNeonへ張られ続けるため、正常時・例外時の両方で
必ずclose()が呼ばれることを実DB接続なしのモックで検証する。
"""
import sys, os
import unittest.mock as mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")  # SQLiteモードでインポート（USE_PG=False）

import database as db
import services.books as books
import services.integrity as integrity


class _FakeCursor:
    def __init__(self, raise_on_execute=None):
        self.raise_on_execute = raise_on_execute
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute

    def fetchone(self):
        return None


class _FakeConn:
    def __init__(self, raise_on_execute=None):
        self.close_call_count = 0
        self.commit_call_count = 0
        self.rollback_call_count = 0
        self._cursor = _FakeCursor(raise_on_execute=raise_on_execute)

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_call_count += 1

    def rollback(self):
        self.rollback_call_count += 1

    def close(self):
        self.close_call_count += 1


# ── _save_genre_update_time ────────────────────────────────────────────────

def test_save_genre_update_time_closes_on_success():
    fake_conn = _FakeConn()
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        books._save_genre_update_time()
    assert fake_conn.commit_call_count == 1
    assert fake_conn.close_call_count == 1


def test_save_genre_update_time_closes_on_exception():
    """execute()がDBエラーで例外を投げても、db_session()のfinallyでcloseされる
    （修正前は except節がログのみでclose()を呼ばず接続がリークしていた）。"""
    fake_conn = _FakeConn(raise_on_execute=RuntimeError("simulated DB error"))
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        books._save_genre_update_time()  # 例外は関数内で握りつぶされ、呼び出し元には伝播しない
    assert fake_conn.commit_call_count == 0
    assert fake_conn.close_call_count == 1, (
        "例外時に接続がclose()されていない（minconn=0下での接続リークの再発）"
    )


# ── _save_audit_time ────────────────────────────────────────────────────────

def test_save_audit_time_closes_on_success():
    fake_conn = _FakeConn()
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        integrity._save_audit_time(checked=10, found=1)
    assert fake_conn.commit_call_count == 1
    assert fake_conn.close_call_count == 1


def test_save_audit_time_closes_on_exception():
    fake_conn = _FakeConn(raise_on_execute=RuntimeError("simulated DB error"))
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        integrity._save_audit_time(checked=10, found=1)
    assert fake_conn.commit_call_count == 0
    assert fake_conn.close_call_count == 1, (
        "例外時に接続がclose()されていない（minconn=0下での接続リークの再発）"
    )


# ── repair_finding（回帰確認：Web/バックグラウンド両方から呼ばれても安全） ──

def test_repair_finding_closes_once_on_success():
    fake_conn = _FakeConn()
    finding_row = {
        "isbn": "9784000000000",
        "db_title": "旧タイトル", "openbd_title": "新タイトル",
        "db_author": "旧著者", "openbd_author": "新著者",
        "db_publisher": "旧出版社", "openbd_publisher": "新出版社",
    }
    with mock.patch.object(integrity, "get_con", return_value=fake_conn), \
         mock.patch.object(integrity, "fetchone", return_value=finding_row):
        result, code = integrity.repair_finding("9784000000000", ["title"], "A000")
    assert code == 200
    assert fake_conn.commit_call_count == 1
    assert fake_conn.close_call_count == 1, "正常終了時にclose()が二重/未実行になっていない"


def test_repair_finding_closes_once_on_exception_mid_operation():
    """UPDATE文の途中で例外が起きても、rollback()の上でclose()が"ちょうど1回"だけ
    呼ばれる（Web経由・バックグラウンド一括修復経由のどちらから呼ばれても同じ関数の
    ため、二重closeやトランザクション範囲の違いは生じない）。"""
    fake_conn = _FakeConn(raise_on_execute=RuntimeError("simulated mid-operation DB error"))
    finding_row = {
        "isbn": "9784000000000",
        "db_title": "旧タイトル", "openbd_title": "新タイトル",
        "db_author": "旧著者", "openbd_author": "新著者",
        "db_publisher": "旧出版社", "openbd_publisher": "新出版社",
    }
    with mock.patch.object(integrity, "get_con", return_value=fake_conn), \
         mock.patch.object(integrity, "fetchone", return_value=finding_row):
        result, code = integrity.repair_finding("9784000000000", ["title"], "A000")
    assert code == 500
    assert fake_conn.rollback_call_count == 1
    assert fake_conn.close_call_count == 1, (
        "例外時にclose()が0回または2回以上呼ばれている（未返却リーク or 二重close）"
    )


def test_repair_finding_context_independent():
    """repair_finding自体はFlaskリクエストコンテキストの有無を一切参照しないため、
    routes/admin.py（Webリクエスト経由）とservices/integrity.py:425（バックグラウンド
    スレッド経由）のどちらから呼ばれても挙動が変わらないことを確認する。"""
    import inspect
    src = inspect.getsource(integrity.repair_finding)
    assert "has_app_context" not in src
    assert "flask" not in src.lower()

"""
2026-08-02 毎起動実行される10件のマイグレーション関数の接続返却安全性テスト。
minconn=0化（別パッチ）により、これらの関数が例外発生時に接続をclose()しないまま
終わると、物理接続が返却されずNeonへ張られ続ける。db_session()化により、正常時・
早期return時・例外時のいずれでも必ず1回close()されることを実DB接続なしで検証する。

対象10関数のうち、内部の各SQL文がすでに個別のtry/except(pass)で保護されている
6関数（card_columns/user_auth_columns/staff_chat/votes_column/type_reply_columns/
db_indices）は、SQLiteモードでは個々のALTER/INDEX失敗が内側で握りつぶされるため、
唯一の保護されていない文である関数末尾の明示的なcon.close()自体が失敗するケースで
外側の安全網（db_session()のfinally）を検証する。
それ以外の4関数（init_db/_migrate_admin_users/_migrate_lib_schedule/_verify_tables）
は内側の保護がないため、最初のSQL実行そのものを失敗させて直接検証する。
"""
import sys, os
import unittest.mock as mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")  # SQLiteモード（USE_PG=False）

import database as db
import migrations


class _FakeCursor:
    def execute(self, sql, params=()):
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConn:
    """get_con()が返す接続の最小限のフェイク。close()は本物のsqlite3.Connection/
    _PooledConnectionと同じく物理的には1回しか実行されない（idempotent）よう
    close_call_countは初回のみ増分する。"""
    def __init__(self, raise_on_execute=False, raise_on_close=False):
        self.raise_on_execute = raise_on_execute
        self.raise_on_close = raise_on_close
        self.close_call_count = 0
        self._closed = False

    def cursor(self):
        if self.raise_on_execute:
            raise RuntimeError("simulated DB error (cursor)")
        return _FakeCursor()

    def execute(self, sql, params=()):
        if self.raise_on_execute:
            raise RuntimeError("simulated DB error (execute)")
        return _FakeCursor()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        if self._closed:
            return  # 本物のsqlite3.Connection/_PooledConnectionと同じくidempotent
        self._closed = True
        self.close_call_count += 1
        if self.raise_on_close:
            raise RuntimeError("simulated DB error (close)")


# ── グループA: 内側に保護がなく、最初のSQL実行失敗が直接外側へ伝播する4関数 ──

def test_init_db_closes_on_exception_and_reraises():
    """init_db()自体には元々except節がなく、呼び出し元(_ensure_db)が例外を捕捉する
    設計のため、db_session()化後も例外はそのまま呼び出し元へ伝播しつつ、接続だけは
    必ずcloseされることを確認する（元の呼び出し元への伝播挙動は変えない）。"""
    fake_conn = _FakeConn(raise_on_execute=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        try:
            migrations.init_db()
            assert False, "例外が呼び出し元に伝播していない（元の挙動が変わっている）"
        except RuntimeError:
            pass
    assert fake_conn.close_call_count == 1, "例外時に接続がclose()されていない"


def test_migrate_admin_users_closes_on_exception():
    fake_conn = _FakeConn(raise_on_execute=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_admin_users()  # 例外は関数内except節で握りつぶされる
    assert fake_conn.close_call_count == 1, "例外時に接続がclose()されていない"


def test_migrate_lib_schedule_closes_on_exception():
    fake_conn = _FakeConn(raise_on_execute=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_lib_schedule()
    assert fake_conn.close_call_count == 1, "例外時に接続がclose()されていない"


def test_verify_tables_closes_on_exception():
    fake_conn = _FakeConn(raise_on_execute=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._verify_tables()
    assert fake_conn.close_call_count == 1, "例外時に接続がclose()されていない"


# ── グループB: 個々のSQL文は内側try/exceptで保護済み。唯一の未保護文である
#    関数末尾の明示的close()自体が失敗するケースで外側安全網を検証する ──

def test_migrate_add_card_columns_survives_close_failure():
    fake_conn = _FakeConn(raise_on_close=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_add_card_columns()  # クラッシュせず外側except節で吸収される
    assert fake_conn.close_call_count == 1, "close()が一度も試みられていない"


def test_migrate_add_user_auth_columns_survives_close_failure():
    fake_conn = _FakeConn(raise_on_close=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_add_user_auth_columns()
    assert fake_conn.close_call_count == 1, "close()が一度も試みられていない"


def test_migrate_add_staff_chat_survives_close_failure():
    fake_conn = _FakeConn(raise_on_close=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_add_staff_chat()
    assert fake_conn.close_call_count == 1, "close()が一度も試みられていない"


def test_migrate_add_votes_column_survives_close_failure():
    fake_conn = _FakeConn(raise_on_close=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_add_votes_column()
    assert fake_conn.close_call_count == 1, "close()が一度も試みられていない"


def test_migrate_add_type_reply_columns_survives_close_failure():
    fake_conn = _FakeConn(raise_on_close=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_add_type_reply_columns()
    assert fake_conn.close_call_count == 1, "close()が一度も試みられていない"


def test_migrate_db_indices_survives_close_failure():
    fake_conn = _FakeConn(raise_on_close=True)
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations._migrate_db_indices()
    assert fake_conn.close_call_count == 1, "close()が一度も試みられていない"


# ── 正常系: 10関数とも、成功時にclose()が二重に物理closeされないことを確認する ──

def test_all_ten_functions_close_exactly_once_on_success():
    targets = [
        migrations._migrate_admin_users,
        migrations._migrate_add_card_columns,
        migrations._migrate_add_user_auth_columns,
        migrations._migrate_add_staff_chat,
        migrations._migrate_add_votes_column,
        migrations._migrate_add_type_reply_columns,
        migrations._migrate_lib_schedule,
        migrations._migrate_db_indices,
        migrations._verify_tables,
    ]
    for func in targets:
        fake_conn = _FakeConn()
        with mock.patch.object(db, "get_con", return_value=fake_conn):
            func()
        assert fake_conn.close_call_count == 1, (
            f"{func.__name__}: 正常終了時にclose()が二重物理close、または未closeになっている"
            f"（実際の呼び出し回数相当の close_call_count={fake_conn.close_call_count}）"
        )

    # init_db()は呼び出し元に例外を伝播させない設計のため正常系のみ個別に確認する
    fake_conn = _FakeConn()
    with mock.patch.object(db, "get_con", return_value=fake_conn):
        migrations.init_db()
    assert fake_conn.close_call_count == 1, "init_db: 正常終了時にclose()が二重/未実行"

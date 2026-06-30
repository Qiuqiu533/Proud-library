"""
database.py のヘルパー関数テスト（SQLite使用）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "")  # SQLiteモードで動作させる

import sqlite3
import database as db


def _make_test_con():
    """テスト用インメモリSQLite接続を返す。"""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    return con


def test_execute_and_fetchone():
    con = _make_test_con()
    db.execute(con, "CREATE TABLE t (id INTEGER, val TEXT)")
    db.execute(con, "INSERT INTO t VALUES (?, ?)", (1, "hello"))
    row = db.fetchone(con, "SELECT val FROM t WHERE id=?", (1,))
    assert row is not None
    assert row["val"] == "hello"


def test_fetchall_returns_list():
    con = _make_test_con()
    db.execute(con, "CREATE TABLE t (n INTEGER)")
    for i in range(3):
        db.execute(con, "INSERT INTO t VALUES (?)", (i,))
    rows = db.fetchall(con, "SELECT n FROM t ORDER BY n")
    assert len(rows) == 3
    assert [r["n"] for r in rows] == [0, 1, 2]


def test_fetchone_missing_returns_none():
    con = _make_test_con()
    db.execute(con, "CREATE TABLE t (id INTEGER)")
    row = db.fetchone(con, "SELECT id FROM t WHERE id=?", (99,))
    assert row is None


def test_placeholder_conversion():
    """? プレースホルダーが SQLite で正しく動作するか確認。"""
    con = _make_test_con()
    db.execute(con, "CREATE TABLE t (a TEXT, b TEXT)")
    db.execute(con, "INSERT INTO t VALUES (?, ?)", ("x", "y"))
    row = db.fetchone(con, "SELECT a, b FROM t WHERE a=?", ("x",))
    assert row["b"] == "y"


def test_db_session_closes_on_success():
    """db_session() は正常終了時に必ず close() する（コネクションプールへ返却）。"""
    closed = {"called": False}

    class FakeConn:
        def close(self):
            closed["called"] = True

    import unittest.mock as mock
    with mock.patch.object(db, "get_con", return_value=FakeConn()):
        with db.db_session() as con:
            assert isinstance(con, FakeConn)
    assert closed["called"], "db_session() exit時にclose()が呼ばれていない"


def test_db_session_closes_on_exception():
    """db_session() は例外発生時もclose()を呼び、コネクションリークを防ぐ。
    本番障害（connection pool exhausted）の再発防止用回帰テスト。
    """
    closed = {"called": False}

    class FakeConn:
        def close(self):
            closed["called"] = True

    import unittest.mock as mock
    with mock.patch.object(db, "get_con", return_value=FakeConn()):
        try:
            with db.db_session() as con:
                raise RuntimeError("simulated DB error mid-operation")
        except RuntimeError:
            pass
    assert closed["called"], "例外発生時にclose()が呼ばれず、接続がリークしている"


def test_pooled_connection_close_is_idempotent():
    """_PooledConnection.close() は二重呼び出ししてもプールへ二重返却しない
    （teardown_appcontextの自動closeと明示closeが重複しても安全）。
    """
    put_calls = {"count": 0}

    class FakePool:
        def putconn(self, conn):
            put_calls["count"] += 1

    import unittest.mock as mock
    with mock.patch.object(db, "_get_pool", return_value=FakePool()):
        pc = db._PooledConnection(conn=object())
        pc.close()
        pc.close()
    assert put_calls["count"] == 1, "close()の二重呼び出しでプールに二重返却された"

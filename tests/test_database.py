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

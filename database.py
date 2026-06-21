import os

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool as pg_pool
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# ── コネクションプール（PostgreSQL のみ） ─────────────────────────────────────
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
    return _pool


class _PooledConnection:
    """プールから借りた接続をラップし、close() でプールに返却する。"""
    def __init__(self, conn):
        self._conn = conn

    def close(self):
        _get_pool().putconn(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def cursor(self):
        return self._conn.cursor()

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_con():
    """DB接続を返す。PG はプールから取得、SQLite はそのまま開く。"""
    if USE_PG:
        return _PooledConnection(_get_pool().getconn())
    else:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        return con


def execute(con, sql, params=()):
    """SQLiteの ? を PostgreSQL の %s に変換して実行する。"""
    if USE_PG:
        sql = sql.replace("?", "%s")
    cur = con.cursor()
    cur.execute(sql, params)
    return cur


def fetchall(con, sql, params=()):
    cur = execute(con, sql, params)
    rows = cur.fetchall()
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    else:
        return [dict(r) for r in rows]


def fetchone(con, sql, params=()):
    cur = execute(con, sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    else:
        return dict(row)

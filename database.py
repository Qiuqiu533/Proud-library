from __future__ import annotations
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

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
_pool: Any = None

def _get_pool() -> Any:
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
    return _pool


class _PooledConnection:
    """プールから借りた接続をラップし、close() でプールに返却する。"""
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._closed = False

    def close(self) -> None:
        # 二重close（明示close() + teardown自動close()）でプールが壊れないようガード
        if self._closed:
            return
        self._closed = True
        _get_pool().putconn(self._conn)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def cursor(self) -> Any:
        return self._conn.cursor()

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def get_con() -> Any:
    """DB接続を返す。PG はプールから取得、SQLite はそのまま開く。
    Flaskリクエスト中に呼ばれた場合、呼び出し側がclose()を忘れても
    teardown_appcontext（app.py側）でリクエスト終了時に自動返却される。
    """
    if USE_PG:
        last_err = None
        for attempt in range(3):
            try:
                con = _PooledConnection(_get_pool().getconn())
                break
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
        else:
            raise last_err
    else:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row

    try:
        from flask import g, has_app_context
        if has_app_context():
            if not hasattr(g, "_db_connections"):
                g._db_connections = []
            g._db_connections.append(con)
    except RuntimeError:
        pass  # Flaskコンテキスト外（スクリプト等）からの呼び出し

    return con


@contextmanager
def db_session() -> Iterator[Any]:
    """`with db_session() as con:` で使う。例外発生時も確実に接続をプールへ返却する。
    バックグラウンドスレッド・スクリプト等、Flaskリクエストコンテキスト外で
    DB接続を使う場合は必ずこれを使うこと（teardown_appcontextの保護が効かないため）。
    """
    con = get_con()
    try:
        yield con
    finally:
        con.close()


def close_request_connections() -> None:
    """リクエスト終了時に未closeの接続をすべてプールへ返却する（teardown_appcontext用）。"""
    try:
        from flask import g
        for con in getattr(g, "_db_connections", []):
            try:
                con.close()
            except Exception:
                pass
    except RuntimeError:
        pass


def execute(con: Any, sql: str, params: tuple = ()) -> Any:
    """SQLiteの ? を PostgreSQL の %s に変換して実行する。"""
    if USE_PG:
        sql = sql.replace("?", "%s")
    cur = con.cursor()
    cur.execute(sql, params)
    return cur


def fetchall(con: Any, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur = execute(con, sql, params)
    rows = cur.fetchall()
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    else:
        return [dict(r) for r in rows]


def fetchone(con: Any, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    cur = execute(con, sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    else:
        return dict(row)

"""
Neon無料枠のコンピュート時間クォータ再枯渇（2026-08-02）を受けた回帰テスト。
psycopg2.connect()のみをモックし、実際のpsycopg2.pool.ThreadedConnectionPoolの
プールロジック本体は本物を使って、minconn=0の挙動を検証する（実DB接続はしない）。
"""
import sys, os
import unittest.mock as mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2
import psycopg2.extensions as _ext
from psycopg2 import pool as pg_pool


class _FakePgConn:
    """psycopg2.connect()が返す接続オブジェクトの最小限のフェイク。
    ThreadedConnectionPool._putconn()が参照する属性・メソッドのみ実装する。
    """
    def __init__(self):
        self.closed = 0
        self.close_call_count = 0
        self.info = mock.Mock()
        self.info.transaction_status = _ext.TRANSACTION_STATUS_IDLE

    def close(self):
        self.close_call_count += 1
        self.closed = 1

    def rollback(self):
        pass


def test_minconn_zero_creates_no_connections_on_init():
    """minconn=0で初期化した場合、プール初期化時にconnect()が一切呼ばれない
    （旧minconn=1では起動直後から1本の物理接続がNeonへ張られていたことに対する回帰テスト）。
    """
    with mock.patch("psycopg2.connect") as mock_connect:
        pool = pg_pool.ThreadedConnectionPool(minconn=0, maxconn=10, dsn="dummy")
        mock_connect.assert_not_called()
        assert pool.minconn == 0


def test_minconn_zero_closes_connection_on_putconn():
    """minconn=0では、getconn()で取得した接続をputconn()で返却すると、
    プールに保持されず必ず物理的にclose()される。
    """
    fake_conn = _FakePgConn()
    with mock.patch("psycopg2.connect", return_value=fake_conn):
        pool = pg_pool.ThreadedConnectionPool(minconn=0, maxconn=10, dsn="dummy")
        conn = pool.getconn()
        assert conn is fake_conn
        assert fake_conn.close_call_count == 0

        pool.putconn(conn)
        assert fake_conn.close_call_count == 1, (
            "minconn=0なのに返却された接続がclose()されていない"
            "（アイドル接続が保持され続けるNeon Scale to Zero阻害の再発リスク）"
        )
        # 内部プールに接続が残っていないことも確認する
        assert len(pool._pool) == 0


def test_minconn_one_would_keep_connection_alive_for_comparison():
    """比較用：旧設定(minconn=1)では返却された接続がプールに保持されclose()されない
    ことを確認し、minconn=0との挙動差を明示する。"""
    fake_conn = _FakePgConn()
    with mock.patch("psycopg2.connect", return_value=fake_conn):
        pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn="dummy")
        # minconn=1の初期化時点で既に1本接続されている
        assert fake_conn.close_call_count == 0
        conn = pool.getconn()
        pool.putconn(conn)
        # minconn=1では len(self._pool) < 1 を満たすためプールに保持され、closeされない
        assert fake_conn.close_call_count == 0
        assert len(pool._pool) == 1


def test_double_close_via_database_module_does_not_double_putconn():
    """database.py の _PooledConnection.close() を二重に呼んでも、
    実際のpsycopg2プールへ二重にputconnされないことを確認する
    （database.py側のガードロジックの回帰テスト、モックプールで検証）。
    """
    os.environ.setdefault("DATABASE_URL", "postgresql://dummy/dummy")
    import importlib
    import database as db
    importlib.reload(db)

    put_calls = {"count": 0}

    class FakePool:
        def putconn(self, conn):
            put_calls["count"] += 1

    with mock.patch.object(db, "_get_pool", return_value=FakePool()):
        pc = db._PooledConnection(conn=object())
        pc.close()
        pc.close()
        pc.close()
    assert put_calls["count"] == 1


def test_database_py_pool_uses_minconn_zero():
    """database.py の _get_pool() が実際に minconn=0 で ThreadedConnectionPool を
    構築していることを、psycopg2.connect呼び出しをモックした上で確認する。
    """
    os.environ["DATABASE_URL"] = "postgresql://dummy/dummy"
    import importlib
    import database as db
    importlib.reload(db)

    # モジュールレベルの_poolキャッシュをリセット
    db._pool = None

    with mock.patch("psycopg2.connect") as mock_connect:
        pool = db._get_pool()
        assert pool.minconn == 0, "database.pyのプールがminconn=0になっていない"
        mock_connect.assert_not_called()

    # 後片付け：他のテストに影響しないようdatabase.pyをSQLiteモードへ戻す
    db._pool = None
    os.environ["DATABASE_URL"] = ""
    importlib.reload(db)

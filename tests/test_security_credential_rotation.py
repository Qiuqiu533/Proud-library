"""
緊急対応（2026-07-18）: templates/index.htmlに平文記載されていた管理者・住民パスワードが
漏洩したため、settingsテーブルのadmin_password/board_password/resident_password行を
キー名ベースで削除するマイグレーションの回帰テスト。
値の照合は行わず、該当キーの行を無条件に削除する挙動であることを確認する。
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("BOARD_PASSWORD", "test-board-pw")
os.environ.setdefault("RESIDENT_PASSWORD", "test-resident-pw")

from database import get_con, execute, fetchone
from migrations import _migrate_clear_leaked_credentials, _migration_done
import config


def test_clear_credentials_deletes_settings_rows_by_key_regardless_of_value():
    con = get_con()
    try:
        execute(con, "DELETE FROM applied_migrations WHERE name=?", ("clear_leaked_credentials_20260718",))
        execute(con, "INSERT INTO settings(key,value) VALUES('admin_password','any-value-a')")
        execute(con, "INSERT INTO settings(key,value) VALUES('board_password','any-value-b')")
        execute(con, "INSERT INTO settings(key,value) VALUES('resident_password','any-value-c')")
        con.commit()

        _migrate_clear_leaked_credentials()

        for key in ("admin_password", "board_password", "resident_password"):
            row = fetchone(con, "SELECT value FROM settings WHERE key=?", (key,))
            assert row is None
    finally:
        con.close()


def test_clear_credentials_is_idempotent_and_flagged_once():
    _migrate_clear_leaked_credentials()
    assert _migration_done("clear_leaked_credentials_20260718") is True
    # 2回目の実行でもエラーにならない（既にフラグが立っていれば即return）
    _migrate_clear_leaked_credentials()


def test_env_password_becomes_effective_after_db_row_removed():
    con = get_con()
    try:
        execute(con, "DELETE FROM applied_migrations WHERE name=?", ("clear_leaked_credentials_20260718",))
        execute(con, "INSERT INTO settings(key,value) VALUES('board_password','some-db-stored-value')")
        con.commit()
    finally:
        con.close()

    _migrate_clear_leaked_credentials()

    # DB保存値の行が削除され、環境変数（BOARD_PASSWORD）の値がフォールバックとして使われる
    assert config.get_board_password() == "test-board-pw"
    assert config.check_password("some-db-stored-value", "board") is False
    assert config.check_password("test-board-pw", "board") is True

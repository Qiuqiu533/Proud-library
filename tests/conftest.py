"""
テスト前にマイグレーションを同期実行してSQLiteのschemaを最新状態に保つ。

2026-07-07: 従来はconftest.py内で個別カラム（awards・user_votes）だけを
その場しのぎでALTERしていたが、lib_scheduleテーブル・ai_summaryカラム等
カバーしていない項目でCI上のテストが失敗していた（本番app.pyの_ensure_db()
はマイグレーションをバックグラウンドスレッドで非同期実行するため、
新規（空）DBに対してテストがマイグレーション完了を待たずに走ってしまう
競合状態が根本原因）。migrations._run_all_migrations()を直接同期呼び出し
することで、個別パッチの追加を今後不要にする。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# config.pyはモジュールレベルで環境変数を読み込むため、migrationsやconfigを
# importする前に設定しておく必要がある（各テストファイル内のsetdefaultは
# pytest_configure実行後のテスト収集フェーズで読まれるため間に合わない）。
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("BOARD_PASSWORD", "test-board-pw")
os.environ.setdefault("RESIDENT_PASSWORD", "test-resident-pw")

from database import USE_PG, get_con, execute


def pytest_configure(config):
    from migrations import init_db, _run_all_migrations
    init_db()
    _run_all_migrations()

    if USE_PG:
        return

    # helpful_votes テーブルのテストデータをリセット（テスト間の状態汚染防止）
    con = get_con()
    try:
        execute(con, "DELETE FROM helpful_votes")
        con.commit()
    except Exception:
        pass
    finally:
        con.close()

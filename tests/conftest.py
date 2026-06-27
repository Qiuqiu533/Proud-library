"""
テスト前にSQLiteマイグレーションを同期実行して schema を最新状態に保つ。
"""
import sqlite3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import USE_PG


def pytest_configure(config):
    if USE_PG:
        return
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.db")
    con = sqlite3.connect(db_path)

    # genre_books.awards カラム
    cols = [r[1] for r in con.execute("PRAGMA table_info(genre_books)")]
    if cols and "awards" not in cols:
        con.execute("ALTER TABLE genre_books ADD COLUMN awards TEXT DEFAULT '[]'")

    # ratings.user_votes カラム
    r_cols = [r[1] for r in con.execute("PRAGMA table_info(ratings)")]
    if r_cols and "user_votes" not in r_cols:
        con.execute("ALTER TABLE ratings ADD COLUMN user_votes TEXT DEFAULT '{{}}'")

    con.commit()
    con.close()

"""
全書籍のジャンルを再分類するスクリプト
手動設定済み（manual_genre=TRUE）の本はスキップ

使い方:
  cd /tmp/Proud-library-fresh
  set -a && source .env.review && set +a
  python3 scripts/reclassify_genres.py [--dry-run]
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", ""))

import argparse
from collections import defaultdict

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _get_con():
    if DATABASE_URL:
        import psycopg2
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        con = psycopg2.connect(url)
        con.autocommit = False
        return con, "%s"
    else:
        import sqlite3
        con = sqlite3.connect(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.db"))
        con.row_factory = sqlite3.Row
        return con, "?"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from services.books import _classify_genre

    con, PH = _get_con()
    cur = con.cursor()

    cur.execute("SELECT isbn, title, description, genre FROM genre_books ORDER BY isbn")
    if DATABASE_URL:
        books = [{"isbn": r[0], "title": r[1], "description": r[2], "genre": r[3]} for r in cur.fetchall()]
    else:
        books = [dict(r) for r in cur.fetchall()]

    print(f"対象: {len(books)} 件  dry-run: {args.dry_run}")

    changed = 0
    unchanged = 0
    genre_counter = defaultdict(int)

    for b in books:
        old_genre = b["genre"] or "その他"
        new_genre = _classify_genre(None, b["title"] or "", b["description"] or "")
        genre_counter[new_genre] += 1

        if old_genre != new_genre:
            changed += 1
            if changed <= 30:
                print(f"  [{b['isbn']}] {(b['title'] or '')[:30]} : {old_genre} → {new_genre}")
            elif changed == 31:
                print("  ... (以下省略)")
            if not args.dry_run:
                cur.execute(f"UPDATE genre_books SET genre={PH} WHERE isbn={PH}", (new_genre, b["isbn"]))
        else:
            unchanged += 1

    if not args.dry_run:
        con.commit()

    print(f"\n変更: {changed} 件 / 変更なし: {unchanged} 件")
    print("\n--- 新ジャンル分布 ---")
    for g, cnt in sorted(genre_counter.items(), key=lambda x: -x[1]):
        print(f"  {g}: {cnt}件")

    con.close()


if __name__ == "__main__":
    main()

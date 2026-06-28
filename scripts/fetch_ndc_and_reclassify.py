"""
OpenBDからNDCコードを取得してDBに保存し、ジャンルを再分類するスクリプト

使い方:
  cd /tmp/Proud-library-fresh
  set -a && source .env.review && set +a
  python3 scripts/fetch_ndc_and_reclassify.py [--dry-run] [--batch-size 500]

オプション:
  --dry-run      DBを更新しない（結果のみ表示）
  --batch-size N OpenBD APIの1回あたりISBN数（デフォルト500）
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import requests
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", ""))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENBD_API = "https://api.openbd.jp/v1/get"


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
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    from services.books import _classify_genre

    con, PH = _get_con()
    cur = con.cursor()

    # 全ISBNを取得
    cur.execute("SELECT isbn, title, author, genre FROM genre_books ORDER BY isbn")
    if DATABASE_URL:
        books = [{"isbn": r[0], "title": r[1], "author": r[2], "genre": r[3]} for r in cur.fetchall()]
    else:
        books = [dict(r) for r in cur.fetchall()]

    isbns = [b["isbn"] for b in books if b["isbn"]]
    book_map = {b["isbn"]: b for b in books}

    print(f"対象: {len(isbns)} 件  dry-run: {args.dry_run}")

    # OpenBDからNDCを500件ずつ取得
    ndc_map = {}
    for i in range(0, len(isbns), args.batch_size):
        batch = isbns[i:i + args.batch_size]
        print(f"  OpenBD取得中... {i+1}〜{min(i+args.batch_size, len(isbns))} 件目")
        try:
            resp = requests.get(OPENBD_API, params={"isbn": ",".join(batch)}, timeout=60)
            for item in resp.json():
                if not item:
                    continue
                try:
                    isbn = item["summary"].get("isbn", "")
                    subjects = item.get("onix", {}).get("DescriptiveDetail", {}).get("Subject", [])
                    ndc = next((s["SubjectCode"] for s in subjects
                                if s.get("SubjectSchemeIdentifier") == "78"), "")
                    if isbn and ndc:
                        ndc_map[isbn] = ndc
                except Exception:
                    pass
        except Exception as e:
            print(f"  ❌ OpenBDエラー: {e}")
        time.sleep(0.3)

    print(f"\nNDC取得済み: {len(ndc_map)} 件 / {len(isbns)} 件")

    # ジャンル再分類
    genre_changed = 0
    ndc_saved = 0
    genre_counter = defaultdict(int)

    for isbn, book in book_map.items():
        ndc = ndc_map.get(isbn, "")
        old_genre = book["genre"] or "その他"
        new_genre = _classify_genre(ndc, book["title"] or "", "")
        genre_counter[new_genre] += 1

        ndc_update = ndc != ""
        genre_update = old_genre != new_genre

        if ndc_update:
            ndc_saved += 1
        if genre_update:
            genre_changed += 1
            if genre_changed <= 20:
                print(f"  [{isbn}] {(book['title'] or '')[:30]} : {old_genre} → {new_genre} (NDC:{ndc or 'なし'})")
            elif genre_changed == 21:
                print("  ... (以下省略)")

        if not args.dry_run and (ndc_update or genre_update):
            cur.execute(
                f"UPDATE genre_books SET ndc={PH}, genre={PH} WHERE isbn={PH}",
                (ndc, new_genre, isbn)
            )

    if not args.dry_run:
        con.commit()
        print(f"\n✅ DB更新完了")

    print(f"\nNDC保存: {ndc_saved} 件 / ジャンル変更: {genre_changed} 件")
    print("\n--- 新ジャンル分布 ---")
    for g, cnt in sorted(genre_counter.items(), key=lambda x: -x[1]):
        print(f"  {g}: {cnt}件")

    con.close()


if __name__ == "__main__":
    main()

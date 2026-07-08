"""
AI書評生成スクリプト v3（CLI）
モデル: gpt-4o-mini

2026-07-08: 生成ロジックをservices/ai_review_generator.pyへ切り出し、
管理画面からの半自動再生成（Phase 1）と共有するようにした。
このファイルはCLI向けの薄いラッパーとして残す（--isbn/--regen等の
細かいオプションはCLI専用）。

使い方:
  cd /tmp/Proud-library-fresh
  set -a && source .env.review && set +a
  python3 scripts/generate_reviews.py [--dry-run] [--limit N] [--isbn ISBN] [--regen]

オプション:
  --dry-run    DBを更新しない
  --limit N    処理件数（デフォルト50）
  --isbn ISBN  特定ISBNのみ処理
  --regen      既存書評も上書き再生成（ai_review_scoreがNULLのものが対象）
  --min-len N  この文字数未満を再生成対象に（デフォルト100）
"""
from __future__ import annotations
import argparse
import os
import sys
import json
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.ai_review_generator import (
    OPENAI_API_KEY, fetch_wikipedia_author, fetch_openbd_meta, generate_with_retry,
)
from database import get_con, USE_PG


def main():
    parser = argparse.ArgumentParser(description="AI書評生成スクリプト v3")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--isbn", type=str, default="")
    parser.add_argument("--regen", action="store_true", help="ai_review_scoreがNULLの既存書評も再生成")
    parser.add_argument("--min-len", type=int, default=100)
    parser.add_argument("--min-score", type=int, default=70, help="この点未満は再生成（デフォルト70）")
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY 環境変数を設定してください")
        sys.exit(1)

    con = get_con()
    cur = con.cursor()
    PH = "%s" if USE_PG else "?"

    if args.isbn:
        cur.execute(
            f"SELECT isbn, title, author, publisher, genre, description FROM genre_books WHERE isbn={PH}",
            (args.isbn,)
        )
    elif args.regen:
        cur.execute(f"""SELECT isbn, title, author, publisher, genre, description
                FROM genre_books
                WHERE (manual_review IS NULL OR manual_review = {"FALSE" if USE_PG else "0"})
                  AND ai_review_date IS NOT NULL
                  AND ai_review_score IS NULL
                ORDER BY isbn
                LIMIT {args.limit}""")
    else:
        cur.execute(f"""SELECT isbn, title, author, publisher, genre, description
                FROM genre_books
                WHERE (manual_review IS NULL OR manual_review = {"FALSE" if USE_PG else "0"})
                  AND (description IS NULL OR LENGTH(description) < {args.min_len})
                ORDER BY isbn
                LIMIT {args.limit}""")

    if USE_PG:
        books = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    else:
        books = [dict(row) for row in cur.fetchall()]
    con.close()

    print(f"対象: {len(books)} 件  dry-run: {args.dry_run}  regen: {args.regen}")

    success = 0
    skipped = 0
    fail = 0

    for book in books:
        isbn = book["isbn"]
        title = book["title"] or ""
        author = book["author"] or ""
        publisher = book["publisher"] or ""
        genre = book["genre"] or ""

        print(f"\n[{isbn}] {title} / {author}")

        meta = fetch_openbd_meta(isbn)
        if meta.get("publisher") and not publisher:
            publisher = meta["publisher"]

        wiki_info = fetch_wikipedia_author(author)
        if wiki_info:
            print(f"  📖 Wikipedia: {wiki_info[:60]}...")

        try:
            result = generate_with_retry(title, author, publisher, genre, wiki_info, args.min_score)

            if result is None:
                print(f"  ⚠️ 情報不足のためスキップ")
                skipped += 1
                continue

            print(f"  → {result['review'][:80]}...")
            print(f"  一言: {result['summary']}")
            print(f"  タグ: {', '.join(result['tags'])}")
            print(f"  自己採点: {result['score']}/100")

            if not args.dry_run:
                con = get_con()
                cur = con.cursor()
                today = datetime.date.today().isoformat()
                tags_json = json.dumps(result["tags"], ensure_ascii=False)
                cur.execute(
                    f"""UPDATE genre_books
                        SET description={PH}, ai_review_date={PH}, ai_review_score={PH},
                            ai_model={PH}, ai_summary={PH}, ai_tags={PH}
                        WHERE isbn={PH}""",
                    (result["review"], today, result["score"], "gpt-4o-mini",
                     result["summary"], tags_json, isbn),
                )
                con.commit()
                con.close()
                print("  ✅ DB更新完了")
            success += 1

        except Exception as e:
            print(f"  ❌ エラー: {e}")
            fail += 1

        time.sleep(0.5)

    print(f"\n完了: 成功 {success} 件 / スキップ {skipped} 件 / 失敗 {fail} 件")


if __name__ == "__main__":
    main()

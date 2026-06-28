"""
NDL（国立国会図書館）APIからNDCコードを取得してDBに保存し、ジャンルを再分類するスクリプト

使い方:
  cd /tmp/Proud-library-fresh
  set -a && source .env.review && set +a
  python3 scripts/fetch_ndc_ndl.py [--dry-run] [--workers N] [--limit N]

オプション:
  --dry-run    DBを更新しない（結果のみ表示）
  --workers N  並列数（デフォルト10）
  --limit N    処理件数上限（デフォルト全件）
"""
from __future__ import annotations
import argparse
import os
import sys
import re
import time
import requests
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", ""))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
NDL_API = "https://iss.ndl.go.jp/api/sru"

# NDL subjectキーワード → ジャンルのマッピング
SUBJECT_GENRE_MAP = [
    (["児童図書", "絵本", "幼児向け"], "絵本・児童書"),
    (["児童文学", "少年少女"], "児童文学"),
    (["推理小説", "ミステリ", "探偵"], "ミステリ・推理"),
    (["時代小説", "歴史小説", "江戸", "武士", "侍", "戦国"], "時代小説・歴史小説"),
    (["SF", "ファンタジー", "異世界", "魔法"], "ファンタジー・SF"),
    (["ホラー", "怪談", "恐怖", "心霊"], "ホラー・怪談"),
    (["恋愛", "純愛", "ラブ"], "恋愛・青春"),
    (["経済", "財政", "金融", "ビジネス", "経営", "投資"], "社会・ノンフィクション"),
    (["政治", "社会", "国際", "外交", "戦争", "歴史的事件"], "社会・ノンフィクション"),
    (["ノンフィクション", "ルポ", "ドキュメント", "伝記", "評伝"], "歴史・伝記"),
    (["料理", "レシピ", "健康", "医療", "育児", "子育て", "ダイエット"], "実用・ハウツー"),
    (["自己啓発", "ビジネス書", "仕事術", "マネジメント"], "実用・ハウツー"),
    (["エッセイ", "随筆", "評論"], "エッセイ・評論"),
    (["歴史", "伝記", "人物"], "歴史・伝記"),
    (["科学", "数学", "物理", "化学", "生物", "天文"], "科学・学術"),
]


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


def fetch_ndc_from_ndl(isbn: str) -> tuple[str, list[str]]:
    """NDL APIからNDCコードとsubjectリストを取得する。"""
    try:
        resp = requests.get(NDL_API, params={
            "operation": "searchRetrieve",
            "version": "1.2",
            "recordSchema": "dcndl",
            "maximumRecords": "1",
            "query": f'isbn="{isbn}"',
        }, timeout=15)
        decoded = unescape(resp.text)
        # ndc9/XXX 形式のNDCを抽出
        ndcs = re.findall(r"ndc9/([0-9.]+)", decoded)
        ndc = ndcs[0] if ndcs else ""
        # subjectキーワードを抽出
        subjects = re.findall(r"<rdf:value>([^<]+)</rdf:value>", decoded)
        return ndc, subjects
    except Exception:
        return "", []


def classify_from_subjects(subjects: list[str]) -> str:
    """subjectキーワードリストからジャンルを判定する。"""
    combined = " ".join(subjects)
    for keywords, genre in SUBJECT_GENRE_MAP:
        if any(kw in combined for kw in keywords):
            return genre
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    from services.books import _classify_genre

    con, PH = _get_con()
    cur = con.cursor()

    # 正規ISBN（978/979始まり）のみ対象
    cur.execute("""
        SELECT isbn, title, genre FROM genre_books
        WHERE isbn LIKE '978%' OR isbn LIKE '979%'
        ORDER BY isbn
    """)
    if DATABASE_URL:
        books = [{"isbn": r[0], "title": r[1], "genre": r[2]} for r in cur.fetchall()]
    else:
        books = [dict(r) for r in cur.fetchall()]

    if args.limit:
        books = books[:args.limit]

    print(f"対象: {len(books)} 件  workers: {args.workers}  dry-run: {args.dry_run}")

    # 並列でNDL APIを叩く
    results = {}  # isbn -> (ndc, subjects)
    done = 0

    def fetch(b):
        ndc, subjects = fetch_ndc_from_ndl(b["isbn"])
        return b["isbn"], ndc, subjects

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch, b): b for b in books}
        for future in as_completed(futures):
            isbn, ndc, subjects = future.result()
            results[isbn] = (ndc, subjects)
            done += 1
            if done % 200 == 0:
                print(f"  NDL取得中... {done}/{len(books)} 件完了")

    ndc_count = sum(1 for ndc, _ in results.values() if ndc)
    print(f"\nNDC取得済み: {ndc_count} 件 / {len(books)} 件")

    # ジャンル再分類
    genre_changed = 0
    genre_counter = defaultdict(int)
    updates = []

    for b in books:
        isbn = b["isbn"]
        ndc, subjects = results.get(isbn, ("", []))
        old_genre = b["genre"] or "その他"

        # NDCで分類 → なければsubjectキーワード → なければ既存ジャンル維持
        if ndc:
            new_genre = _classify_genre(ndc, b["title"] or "", "")
        else:
            new_genre = classify_from_subjects(subjects)
            if not new_genre:
                new_genre = old_genre  # 変更しない

        genre_counter[new_genre] += 1

        if old_genre != new_genre or ndc:
            updates.append((ndc, new_genre, isbn))
            if old_genre != new_genre:
                genre_changed += 1
                if genre_changed <= 20:
                    print(f"  [{isbn}] {(b['title'] or '')[:30]} : {old_genre} → {new_genre} (NDC:{ndc or 'subject'})")
                elif genre_changed == 21:
                    print("  ... (以下省略)")

    if not args.dry_run and updates:
        # 長時間のAPI取得後は接続が切れている可能性があるため再接続
        try:
            con.close()
        except Exception:
            pass
        con2, PH2 = _get_con()
        cur2 = con2.cursor()
        batch_size = 200
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            for ndc, new_genre, isbn in batch:
                cur2.execute(
                    f"UPDATE genre_books SET ndc={PH2}, genre={PH2} WHERE isbn={PH2}",
                    (ndc, new_genre, isbn)
                )
            con2.commit()
            print(f"  DB更新中... {min(i+batch_size, len(updates))}/{len(updates)} 件")
        con2.close()
        print(f"\n✅ DB更新完了 ({len(updates)} 件)")

    print(f"\nジャンル変更: {genre_changed} 件")
    print("\n--- 新ジャンル分布（正規ISBN分） ---")
    for g, cnt in sorted(genre_counter.items(), key=lambda x: -x[1]):
        print(f"  {g}: {cnt}件")

    con.close()


if __name__ == "__main__":
    main()

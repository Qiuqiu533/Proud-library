"""
PLAM CSV → award_books テーブル 同期スクリプト
実行: DATABASE_URL=... python3 scripts/sync_plam_to_award_books.py [--dry-run]
"""
import csv
import os
import sys
import unicodedata

# PLAM award_id → award_books の award 名マッピング
AWARD_MAP = {
    "AKU": "芥川賞",
    "NAO": "直木賞",
    "JRA": "日本推理作家協会賞",
    "HKM": "本格ミステリ大賞",
    "HON": "本屋大賞",
    "YAM": "山本周五郎賞",
    "KMS": "このミステリーがすごい！国内1位",
    "RAN": "江戸川乱歩賞",
    "KIK": "吉川英治文学賞",
    "JSF": "日本SF大賞",
    "HOR": "日本ホラー小説大賞",
}

def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").strip()
    return "".join(s.split())

def main():
    dry_run = "--dry-run" in sys.argv

    base = os.path.join(os.path.dirname(__file__), "..", "data", "plam")
    works = {r["work_id"]: r for r in csv.DictReader(open(os.path.join(base, "works.csv")))}
    history = list(csv.DictReader(open(os.path.join(base, "award_history.csv"))))

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from database import get_con, execute, fetchall

    con = get_con()

    # 既存エントリの (award, normalized_title) セット
    existing_rows = fetchall(con, "SELECT award, title FROM award_books")
    existing = {(_norm(r["title"]), r["award"]) for r in existing_rows}
    print(f"既存 award_books: {len(existing_rows)} 件")

    inserted = 0
    skipped = 0

    for row in history:
        award_id = row["award_id"]
        award_name = AWARD_MAP.get(award_id)
        if not award_name:
            continue

        work = works.get(row["work_id"])
        if not work:
            continue

        title = work["canonical_title"] or work["title"]
        author = work["author"]
        isbn13 = work.get("isbn13", "").strip()
        award_year = int(row["award_year"]) if row.get("award_year") else None
        award_no = int(row["award_no"]) if row.get("award_no") else None

        key = (_norm(title), award_name)
        if key in existing:
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY] INSERT: {award_name} {award_year}回{award_no} 『{title}』 {author}")
        else:
            execute(
                con,
                "INSERT INTO award_books (award, award_no, award_year, title, author, isbn13, status) VALUES (?,?,?,?,?,?,?)",
                (award_name, award_no, award_year, title, author, isbn13 or None, "確認済"),
            )
            existing.add(key)

        inserted += 1

    if not dry_run:
        con.commit()
    con.close()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}追加: {inserted} 件 / スキップ（既存）: {skipped} 件")

if __name__ == "__main__":
    main()

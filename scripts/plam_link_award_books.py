"""
plam_link_award_books.py — award_books ↔ PLAM works のマッピングを実行する。

使い方:
    python scripts/plam_link_award_books.py --dry-run   # 照合結果を表示のみ
    python scripts/plam_link_award_books.py --apply     # DBに反映
    python scripts/plam_link_award_books.py --stats     # 現在のマッチ率を表示
"""
import argparse
import csv
import sys
import unicodedata
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PLAM_DIR = ROOT / "data" / "plam"


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower()
    s = re.sub(r"[\s　]+", "", s)
    return s


def _load_plam_works() -> dict[str, dict]:
    """canonical_title正規化 → works行 のインデックス"""
    result: dict[str, dict] = {}
    with open(PLAM_DIR / "works.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("canonical_title", "")
            if t:
                result[_normalize(t)] = row
    return result


def _match(title: str, author: str, plam_idx: dict[str, dict]) -> tuple[str, str]:
    """(work_id, confidence) を返す。未マッチは ('', '')"""
    key = _normalize(title)
    work = plam_idx.get(key)
    if work:
        # 著者確認（片方が空なら許容）
        pa = _normalize(work.get("author", ""))
        qa = _normalize(author or "")
        if not pa or not qa or pa == qa or pa in qa or qa in pa:
            return work["work_id"], "exact"
        return work["work_id"], "title_only"

    # 前方一致フォールバック（3文字以上）
    if len(key) >= 3:
        for k, v in plam_idx.items():
            if k.startswith(key) or key.startswith(k):
                return v["work_id"], "partial"

    return "", ""


def cmd_stats(con):
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済'")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済' AND plam_work_id IS NOT NULL")
    linked = cur.fetchone()[0]
    print(f"award_books 確認済み: {total}件")
    print(f"PLAM連携済み:         {linked}件  ({linked/total*100:.1f}%)" if total else "データなし")

    # 賞別
    cur.execute("""
        SELECT award,
               COUNT(*) total,
               COUNT(plam_work_id) linked
        FROM award_books WHERE status='確認済'
        GROUP BY award ORDER BY award
    """)
    print("\n賞別マッチ率:")
    for r in cur.fetchall():
        pct = r[2] / r[1] * 100 if r[1] else 0
        bar = "█" * int(pct / 5)
        print(f"  {r[0]:<20} {r[2]:>3}/{r[1]:<3} ({pct:>5.1f}%) {bar}")


def cmd_dry_run(con, plam_idx):
    cur = con.cursor()
    cur.execute("SELECT id, award, title, author FROM award_books WHERE status='確認済' AND plam_work_id IS NULL ORDER BY award, id")
    rows = cur.fetchall()
    if not rows:
        print("未マッチの行はありません。")
        return

    matched = []
    unmatched = []
    for row in rows:
        rid, award, title, author = row
        wid, conf = _match(title, author or "", plam_idx)
        if wid:
            matched.append((rid, award, title, wid, conf))
        else:
            unmatched.append((rid, award, title))

    print(f"\n=== マッチ結果 ===")
    print(f"対象: {len(rows)}件  マッチ: {len(matched)}件  未マッチ: {len(unmatched)}件")
    print(f"マッチ率: {len(matched)/len(rows)*100:.1f}%\n")

    print("--- マッチ ---")
    for rid, award, title, wid, conf in matched:
        print(f"  [{conf:10}] {award} / {title}  →  {wid}")

    if unmatched:
        print(f"\n--- 未マッチ ({len(unmatched)}件) ---")
        for rid, award, title in unmatched:
            print(f"  {award} / {title}")


def cmd_apply(con, plam_idx):
    cur = con.cursor()
    cur.execute("SELECT id, award, title, author FROM award_books WHERE status='確認済' AND plam_work_id IS NULL")
    rows = cur.fetchall()

    updated = 0
    for row in rows:
        rid, award, title, author = row
        wid, conf = _match(title, author or "", plam_idx)
        if wid:
            cur.execute("UPDATE award_books SET plam_work_id=%s WHERE id=%s", (wid, rid))
            updated += 1

    con.commit()
    print(f"award_books.plam_work_id 更新完了: {updated}件 / {len(rows)}件")

    # カバレッジ履歴を記録
    cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済'")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済' AND plam_work_id IS NOT NULL")
    linked = cur.fetchone()[0]
    pct = round(linked / total * 100, 1) if total else 0
    try:
        cur.execute(
            "INSERT INTO plam_coverage_log (total, linked, coverage_pct, note) VALUES (%s, %s, %s, %s)",
            (total, linked, pct, f"apply +{updated}件")
        )
        con.commit()
        print(f"カバレッジ履歴記録: {pct}% ({linked}/{total})")
    except Exception as e:
        print(f"[warn] 履歴記録スキップ: {e}")


def main():
    parser = argparse.ArgumentParser(description="award_books ↔ PLAM マッピング")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply",   action="store_true")
    group.add_argument("--stats",   action="store_true")
    args = parser.parse_args()

    from database import get_con, USE_PG
    if not USE_PG:
        print("このスクリプトはPostgreSQL環境（本番）でのみ動作します。")
        sys.exit(1)

    plam_idx = _load_plam_works()
    print(f"PLAMインデックス: {len(plam_idx)}作品")

    con = get_con()
    try:
        if args.stats:
            cmd_stats(con)
        elif args.dry_run:
            cmd_dry_run(con, plam_idx)
        elif args.apply:
            cmd_apply(con, plam_idx)
    finally:
        con.close()


if __name__ == "__main__":
    main()

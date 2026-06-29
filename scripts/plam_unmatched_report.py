"""
plam_unmatched_report.py — 未リンク受賞作の原因分類レポートを生成する。

使い方:
    python scripts/plam_unmatched_report.py              # コンソール表示
    python scripts/plam_unmatched_report.py --csv        # plam_unmatched_YYYYMMDD.csv 出力
    python scripts/plam_unmatched_report.py --csv --out /tmp/report.csv

未リンク原因カテゴリ:
    title_variant   — タイトル揺れ（正規化後に部分一致あり）
    author_mismatch — タイトル一致するがPLAMの著者と不一致
    plam_missing    — PLAM works.csv に収録なし（データ拡張候補）
    short_title     — タイトルが2文字以下（照合困難）
"""
import argparse
import csv
import sys
import unicodedata
import re
from datetime import date
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
    result: dict[str, dict] = {}
    with open(PLAM_DIR / "works.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("canonical_title", "")
            if t:
                result[_normalize(t)] = row
    return result


def _classify(title: str, author: str, plam_idx: dict[str, dict]) -> dict:
    """未リンク行の原因を分類して返す"""
    key = _normalize(title)

    if len(key) <= 2:
        return {"reason": "short_title", "plam_title": "", "plam_author": "", "note": f"タイトル{len(key)}文字"}

    # 完全一致（著者不一致）
    exact = plam_idx.get(key)
    if exact:
        return {
            "reason": "author_mismatch",
            "plam_title": exact.get("canonical_title", ""),
            "plam_author": exact.get("author", ""),
            "note": f"PLAM著者={exact.get('author','?')} / DB著者={author or '（空）'}",
        }

    # 部分一致（タイトル揺れ候補）
    best = None
    best_score = 0
    for k, v in plam_idx.items():
        if k.startswith(key) or key.startswith(k):
            score = min(len(k), len(key)) / max(len(k), len(key))
            if score > best_score:
                best, best_score = v, score

    if best and best_score >= 0.6:
        return {
            "reason": "title_variant",
            "plam_title": best.get("canonical_title", ""),
            "plam_author": best.get("author", ""),
            "note": f"類似度{best_score:.0%} → '{best.get('canonical_title','')}'"
        }

    return {"reason": "plam_missing", "plam_title": "", "plam_author": "", "note": "PLAM未収録（追加候補）"}


def build_report(con, plam_idx: dict[str, dict]) -> list[dict]:
    cur = con.cursor()
    cur.execute("""
        SELECT id, award, award_year, title, author
        FROM award_books
        WHERE status='確認済' AND plam_work_id IS NULL
        ORDER BY award, award_year DESC NULLS LAST
    """)
    rows = cur.fetchall()

    records = []
    for rid, award, year, title, author in rows:
        info = _classify(title, author or "", plam_idx)
        records.append({
            "id": rid,
            "award": award,
            "year": year or "",
            "title": title,
            "author": author or "",
            **info,
        })
    return records


def print_summary(records: list[dict]):
    from collections import Counter
    reasons = Counter(r["reason"] for r in records)
    total = len(records)

    labels = {
        "title_variant":   "タイトル揺れ（正規化で近似あり）",
        "author_mismatch": "著者名不一致（タイトル一致）",
        "plam_missing":    "PLAM未収録（データ拡張候補）",
        "short_title":     "タイトル短すぎ（照合困難）",
    }

    print(f"\n=== 未リンク原因分類 ({total}件) ===\n")
    for reason, label in labels.items():
        n = reasons.get(reason, 0)
        bar = "█" * int(n / max(total, 1) * 30)
        print(f"  {label:<30} {n:>3}件  {bar}")

    print("\n--- plam_missing（追加候補） ---")
    missing = [r for r in records if r["reason"] == "plam_missing"][:20]
    for r in missing:
        print(f"  {r['year'] or '？'}年 {r['award']} ／ {r['title']}  著: {r['author'] or '?'}")

    print("\n--- title_variant（揺れ候補） ---")
    variants = [r for r in records if r["reason"] == "title_variant"][:15]
    for r in variants:
        print(f"  DB: 「{r['title']}」→ PLAM候補: 「{r['plam_title']}」 {r['note']}")

    print("\n--- author_mismatch ---")
    mismatches = [r for r in records if r["reason"] == "author_mismatch"][:10]
    for r in mismatches:
        print(f"  「{r['title']}」  {r['note']}")


def write_csv(records: list[dict], out_path: Path):
    fields = ["id", "award", "year", "title", "author", "reason", "plam_title", "plam_author", "note"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    print(f"\nCSV出力: {out_path}  ({len(records)}件)")


def main():
    parser = argparse.ArgumentParser(description="未リンク受賞作の原因分類レポート")
    parser.add_argument("--csv", action="store_true", help="CSVファイルを出力する")
    parser.add_argument("--out", type=str, default="", help="CSV出力パス（デフォルト: カレントディレクトリ）")
    args = parser.parse_args()

    from database import get_con, USE_PG
    if not USE_PG:
        print("このスクリプトはPostgreSQL環境（本番）でのみ動作します。")
        sys.exit(1)

    plam_idx = _load_plam_works()
    print(f"PLAMインデックス: {len(plam_idx)}作品")

    con = get_con()
    try:
        records = build_report(con, plam_idx)
    finally:
        con.close()

    print_summary(records)

    if args.csv:
        out = Path(args.out) if args.out else Path(f"plam_unmatched_{date.today().strftime('%Y%m%d')}.csv")
        write_csv(records, out)


if __name__ == "__main__":
    main()

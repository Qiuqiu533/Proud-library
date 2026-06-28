"""
PLAM Version 1.4 — award_history.csv 生成スクリプト

各賞CSV（akutagawa_prize.csv, naoki_prize.csv 等）から
award_history.csv を生成する。

award_history.csv は:
- 作品受賞履歴の一元管理ファイル
- すべての賞CSVが更新されたときに再生成する
- worksの唯一マスターは works.csv（ISBN・タイトル修正はここだけ行う）

テーブル設計（将来DBへのインポート用）:
  history_id  INTEGER PRIMARY KEY AUTOINCREMENT
  work_id     TEXT NOT NULL REFERENCES works(work_id)
  award_id    TEXT NOT NULL
  award_year  INTEGER NOT NULL
  award_no    INTEGER
  award_term  TEXT
  status      TEXT NOT NULL  -- awarded / co_winner
  remarks     TEXT

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_build_award_history.py [--dry-run]
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path

PLAM_DIR = Path("data/plam")
EXCLUDE   = {"awards_master.csv", "works.csv", "authors.csv", "aliases.csv", "award_history.csv"}
HISTORY_PATH = PLAM_DIR / "award_history.csv"
FIELDNAMES = ["history_id", "work_id", "award_id", "award_year",
              "award_no", "award_term", "status", "remarks"]


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # 全賞CSVを読み込み
    history_rows: list[dict] = []
    award_files = sorted(p for p in PLAM_DIR.glob("*.csv") if p.name not in EXCLUDE)

    for csv_path in award_files:
        rows = read_csv(csv_path)
        if not rows:
            continue
        if "work_id" not in rows[0] or "award_id" not in rows[0]:
            print(f"  スキップ: {csv_path.name}（award_idまたはwork_id列がない）")
            continue

        added = 0
        for r in rows:
            # no_award行は history に含めない
            if r.get("status") == "no_award":
                continue

            work_id = (r.get("work_id") or "").strip()
            award_id = (r.get("award_id") or "").strip()
            if not work_id:
                print(f"  ⚠️  work_id欠損: {r.get('entry_id', '?')} ({csv_path.name})")
                continue

            history_rows.append({
                "history_id": "",  # 採番は書き出し時
                "work_id":    work_id,
                "award_id":   award_id,
                "award_year": r.get("award_year", ""),
                "award_no":   r.get("award_no", ""),
                "award_term": r.get("award_term", ""),
                "status":     r.get("status", ""),
                "remarks":    r.get("remarks", ""),
            })
            added += 1
        print(f"  {csv_path.name}: {added} 行")

    # history_id を連番で付与
    for i, row in enumerate(history_rows, start=1):
        row["history_id"] = i

    # 複数受賞のワーク検出（参考表示）
    from collections import defaultdict
    work_awards: dict[str, list[str]] = defaultdict(list)
    for r in history_rows:
        work_awards[r["work_id"]].append(r["award_id"])
    multi_award = {wid: awards for wid, awards in work_awards.items() if len(awards) > 1}
    if multi_award:
        print(f"\n📚 複数受賞作品: {len(multi_award)} 件")
        for wid, awards in list(multi_award.items())[:5]:
            print(f"  {wid}: {awards}")
    else:
        print("\n  複数受賞作品: なし（現時点）")

    print(f"\naward_history 合計: {len(history_rows)} 行")

    if not args.dry_run:
        with open(HISTORY_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(history_rows)
        print(f"✅ {HISTORY_PATH} 生成完了")
    else:
        print("[dry-run] 書き込みなし")


if __name__ == "__main__":
    main()

"""
PLAM Version 1.2 移行スクリプト
- 賞別CSVの work_id → entry_id にリネーム
- 作品共通 work_id（PLAM-XXXXXX）を採番
- data/plam/works.csv を自動生成

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_assign_work_ids.py [--dry-run]
"""
from __future__ import annotations
import argparse, csv, re, sys
from pathlib import Path
from collections import OrderedDict

PLAM_DIR = Path("data/plam")
AWARD_CSVS = sorted(PLAM_DIR.glob("*.csv"))
EXCLUDE = {"awards_master.csv", "works.csv", "authors.csv", "aliases.csv"}


def read_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    reader = csv.DictReader(lines)
    return list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    header_comments = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                header_comments.append(line)
            else:
                break

    with open(path, "w", encoding="utf-8", newline="") as f:
        # コメント行を保持
        for c in header_comments:
            f.write(c)
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_key(title: str, author: str) -> str:
    """title+author を正規化して重複検出キーにする"""
    t = re.sub(r"[\s　・〜～／/]", "", title).lower()
    a = re.sub(r"[\s　]", "", author).lower()
    return f"{t}||{a}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # ── 全CSVを読み込み ─────────────────────────────
    all_files: dict[Path, list[dict]] = {}
    for csv_path in AWARD_CSVS:
        if csv_path.name in EXCLUDE:
            continue
        rows = read_csv(csv_path)
        if not rows:
            continue
        all_files[csv_path] = rows

    # ── work_id の採番 ──────────────────────────────
    # 既存のwork_id（PLAM-XXXXXX形式）があれば再利用
    existing: dict[str, str] = {}   # normalize_key → PLAM ID
    counter = 1

    def next_plam_id() -> str:
        nonlocal counter
        pid = f"PLAM-{counter:06d}"
        counter += 1
        return pid

    # 1周目: 既存のPLAM IDを収集（既に移行済みの場合）
    for path, rows in all_files.items():
        if "work_id" not in rows[0]:
            continue
        for r in rows:
            wid = r.get("work_id", "")
            if wid and wid.startswith("PLAM-") and r.get("title") and r.get("author"):
                key = normalize_key(r["title"], r["author"])
                if key not in existing:
                    existing[key] = wid
                    num = int(wid.replace("PLAM-", ""))
                    if num >= counter:
                        counter = num + 1

    # 2周目: 新しい行に採番
    works_map: OrderedDict[str, dict] = OrderedDict()

    updated: dict[Path, list[dict]] = {}
    for path, rows in all_files.items():
        first = rows[0]
        # entry_id列の有無を確認
        has_entry_id = "entry_id" in first
        # 旧形式（work_idが賞ID依存）か新形式（PLAM-）かを判定
        old_work_id_col = "work_id" in first and not has_entry_id

        new_rows = []
        for r in rows:
            new_r = dict(r)

            if r.get("status") == "no_award":
                # no_award はwork_idなし
                new_r["entry_id"] = r.get("work_id", r.get("entry_id", ""))
                new_r["work_id"] = ""
                new_rows.append(new_r)
                continue

            title  = (r.get("title") or "").strip()
            author = (r.get("author") or "").strip()

            if not title or not author:
                new_r["entry_id"] = r.get("work_id", r.get("entry_id", ""))
                new_r["work_id"] = ""
                new_rows.append(new_r)
                continue

            key = normalize_key(title, author)

            # entry_id = 旧 work_id（賞依存ID）
            old_id = r.get("work_id", r.get("entry_id", ""))
            if not has_entry_id:
                # 旧形式: work_id が AKU-xxx 形式
                new_r["entry_id"] = old_id
            # else すでに entry_id あり

            # work_id 採番
            if key in existing:
                plam_id = existing[key]
            else:
                plam_id = next_plam_id()
                existing[key] = plam_id

            new_r["work_id"] = plam_id

            # works_map に追加
            if plam_id not in works_map:
                works_map[plam_id] = {
                    "work_id": plam_id,
                    "title": title,
                    "author": author,
                    "isbn13": r.get("isbn13", ""),
                    "isbn_status": r.get("isbn_status", "missing"),
                    "notes": "",
                }

            new_rows.append(new_r)

        updated[path] = new_rows

    # ── 出力 ────────────────────────────────────────
    work_total = len(works_map)
    print(f"作品マスター: {work_total} 件")

    for path, rows in updated.items():
        if not rows:
            continue
        # 列順を決定
        sample = rows[0]
        # 標準列順
        standard = ["entry_id", "work_id", "award_id", "award_name", "award_year",
                    "award_no", "award_term", "title", "author",
                    "isbn13", "isbn_status", "status", "remarks"]
        existing_keys = list(sample.keys())
        fieldnames = [f for f in standard if f in existing_keys or f in ("entry_id", "work_id")]
        # 不足列をデフォルト補完
        for r in rows:
            r.setdefault("entry_id", "")
            r.setdefault("work_id", "")

        print(f"  {path.name}: {len(rows)} レコード → entry_id/work_id 付与")
        if not args.dry_run:
            write_csv(path, fieldnames, rows)

    # works.csv を生成
    works_path = PLAM_DIR / "works.csv"
    print(f"\n  works.csv: {work_total} 件")
    if not args.dry_run:
        with open(works_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["work_id","title","author","isbn13","isbn_status","notes"])
            w.writeheader()
            w.writerows(works_map.values())
        print(f"  ✅ {works_path} 生成完了")

    if args.dry_run:
        print("\n[dry-run] 実際には書き込みませんでした")
    else:
        print("\n✅ Version 1.2 移行完了")


if __name__ == "__main__":
    main()

"""
PLAM Version 1.3 構築スクリプト

実行すること:
1. works.csv から authors.csv を自動生成（author_id付与）
2. works.csv に canonical_title・author_id 列を追加
3. aliases.csv の雛形を生成（空）
4. 重複候補レポート生成（タイトルのみ一致）

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_build_v13.py [--dry-run]
"""
from __future__ import annotations
import argparse, csv, re
from pathlib import Path
from collections import defaultdict

PLAM_DIR = Path("data/plam")


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


def normalize(s: str) -> str:
    return re.sub(r"[\s　・〜～／/（）()、。]", "", s).lower()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    works_path = PLAM_DIR / "works.csv"
    authors_path = PLAM_DIR / "authors.csv"
    aliases_path = PLAM_DIR / "aliases.csv"

    works = read_csv(works_path)

    # ── 1. authors.csv 生成 ────────────────────────
    # 既存のauthor_idを読み込み（再実行時に継続）
    existing_author_ids: dict[str, str] = {}  # normalize(name) → author_id
    author_counter = 1

    if authors_path.exists():
        for r in read_csv(authors_path):
            key = normalize(r.get("author_name", ""))
            if key:
                existing_author_ids[key] = r["author_id"]
                num = int(r["author_id"].replace("AUTR-", ""))
                if num >= author_counter:
                    author_counter = num + 1

    authors_map: dict[str, dict] = {}  # author_id → row
    # 既存を先に復元
    if authors_path.exists():
        for r in read_csv(authors_path):
            authors_map[r["author_id"]] = r

    work_to_author: dict[str, str] = {}  # work_id → author_id

    for w in works:
        author = (w.get("author") or "").strip()
        if not author:
            continue
        key = normalize(author)
        if key in existing_author_ids:
            aid = existing_author_ids[key]
        else:
            aid = f"AUTR-{author_counter:06d}"
            author_counter += 1
            existing_author_ids[key] = aid

        if aid not in authors_map:
            authors_map[aid] = {
                "author_id": aid,
                "author_name": author,
                "author_name_kana": "",
                "birth_year": "",
                "death_year": "",
                "notes": "",
            }

        if w.get("work_id"):
            work_to_author[w["work_id"]] = aid

    print(f"著者マスター: {len(authors_map)} 件")

    # ── 2. works.csv に canonical_title・author_id 追加 ──
    new_works = []
    for w in works:
        nw = dict(w)
        nw.setdefault("canonical_title", w.get("title", ""))
        nw["author_id"] = work_to_author.get(w.get("work_id", ""), "")
        new_works.append(nw)

    # ── 3. タイトルのみ一致の重複候補検出 ───────────
    title_to_works: dict[str, list[dict]] = defaultdict(list)
    for w in new_works:
        t = normalize(w.get("title", ""))
        if t:
            title_to_works[t].append(w)

    duplicate_candidates = [
        ws for ws in title_to_works.values()
        if len(ws) > 1 and len({normalize(x.get("author","")) for x in ws}) > 1
    ]
    if duplicate_candidates:
        print(f"\n⚠️  タイトル一致・著者不一致（要確認）: {len(duplicate_candidates)} 件")
        for ws in duplicate_candidates[:5]:
            print(f"  タイトル: {ws[0]['title']}")
            for x in ws:
                print(f"    {x['work_id']}  {x['author']}")
    else:
        print("✅ タイトル重複候補: なし")

    if not args.dry_run:
        # authors.csv 書き出し
        fieldnames = ["author_id","author_name","author_name_kana","birth_year","death_year","notes"]
        with open(authors_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(sorted(authors_map.values(), key=lambda x: x["author_id"]))
        print(f"\n✅ {authors_path} 生成完了 ({len(authors_map)} 件)")

        # works.csv 書き出し（列追加）
        fieldnames_w = ["work_id","canonical_title","title","author","author_id",
                        "isbn13","isbn_status","notes"]
        with open(works_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames_w, extrasaction="ignore")
            w.writeheader()
            w.writerows(new_works)
        print(f"✅ {works_path} 更新完了 (canonical_title, author_id 追加)")

        # aliases.csv 雛形生成（未存在の場合のみ）
        if not aliases_path.exists():
            with open(aliases_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["type","canonical_id","alias","notes"])
                w.writeheader()
            print(f"✅ {aliases_path} 雛形生成（空）")
            print("  type: work=作品別名 / author=著者別名")
            print("  canonical_id: work_id or author_id")
    else:
        print("\n[dry-run] 書き込みなし")


if __name__ == "__main__":
    main()

"""
PLAM Version 2.0/2.1 — 拡張分析スクリプト

機能:
  --similarity      award_similarity.csv を生成（Jaccard係数）
  --graph           graph_data.csv を生成（D3.js/Cytoscape等向けグラフデータ）
  --validate-master awards_master.csv と実際のインポート済み賞を照合

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_build_v20.py --similarity
  python3 scripts/plam_build_v20.py --graph
"""
from __future__ import annotations
import argparse, csv, itertools
from pathlib import Path
from collections import defaultdict

PLAM_DIR  = Path("data/plam")
REPORTS_DIR = Path("reports")

HISTORY_PATH   = PLAM_DIR / "award_history.csv"
MASTER_PATH    = PLAM_DIR / "awards_master.csv"
SIMILARITY_PATH = PLAM_DIR / "award_similarity.csv"
SIMILARITY_FIELDS = ["award_a", "award_b", "jaccard", "shared_works",
                     "works_a", "works_b", "shared_titles"]
GRAPH_PATH   = PLAM_DIR / "graph_data.csv"
GRAPH_FIELDS = ["source", "target", "weight", "shared_works", "shared_titles"]


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


def _build_similarity():
    history = _read_csv(HISTORY_PATH)

    # award_id → work_id set
    award_works: dict[str, set[str]] = defaultdict(set)
    for r in history:
        wid = (r.get("work_id") or "").strip()
        aid = (r.get("award_id") or "").strip()
        if wid and aid:
            award_works[aid].add(wid)

    # work_id → title（works.csv から）
    works_path = PLAM_DIR / "works.csv"
    wid_title: dict[str, str] = {}
    if works_path.exists():
        for r in _read_csv(works_path):
            wid_title[r["work_id"]] = r.get("canonical_title", "")

    award_ids = sorted(award_works.keys())
    rows: list[dict] = []

    for a, b in itertools.combinations(award_ids, 2):
        set_a = award_works[a]
        set_b = award_works[b]
        inter = set_a & set_b
        union = set_a | set_b
        jaccard = round(len(inter) / len(union), 4) if union else 0.0
        titles = "; ".join(sorted(wid_title.get(w, w) for w in inter)[:5])
        rows.append({
            "award_a":      a,
            "award_b":      b,
            "jaccard":      jaccard,
            "shared_works": len(inter),
            "works_a":      len(set_a),
            "works_b":      len(set_b),
            "shared_titles": titles,
        })

    # Jaccard 降順でソート
    rows.sort(key=lambda r: float(r["jaccard"]), reverse=True)

    with open(SIMILARITY_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SIMILARITY_FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"✅ {SIMILARITY_PATH} 生成完了（{len(rows)} ペア）")
    print("\n上位10ペア:")
    for r in rows[:10]:
        print(f"  {r['award_a']} ↔ {r['award_b']}: {r['jaccard']} "
              f"（{r['shared_works']}件 / {r['works_a']}+{r['works_b']}）")


def _build_graph():
    """Jaccard係数をエッジweightとしたグラフデータ（D3.js/Cytoscape向け）を生成。
    閾値 > 0（共有作品が1件以上）のペアのみ出力。
    """
    if not SIMILARITY_PATH.exists():
        print("award_similarity.csv が見つかりません。先に --similarity を実行してください。")
        return

    rows_out: list[dict] = []
    with open(SIMILARITY_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if float(r["jaccard"]) > 0:
                rows_out.append({
                    "source":        r["award_a"],
                    "target":        r["award_b"],
                    "weight":        r["jaccard"],
                    "shared_works":  r["shared_works"],
                    "shared_titles": r["shared_titles"],
                })

    rows_out.sort(key=lambda r: float(r["weight"]), reverse=True)

    with open(GRAPH_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GRAPH_FIELDS)
        w.writeheader()
        w.writerows(rows_out)

    print(f"✅ {GRAPH_PATH} 生成完了（{len(rows_out)} エッジ）")
    print("\nエッジ一覧:")
    for r in rows_out:
        print(f"  {r['source']} → {r['target']}: weight={r['weight']} "
              f"({r['shared_works']}作品: {r['shared_titles'][:40]})")


def _validate_master():
    master = _read_csv(MASTER_PATH)
    history = _read_csv(HISTORY_PATH)

    master_ids = {r["award_id"] for r in master}
    history_ids = {(r.get("award_id") or "").strip() for r in history if r.get("award_id")}

    imported = history_ids - {""}
    in_master_not_imported = {a for a in master_ids
                               if _read_csv(MASTER_PATH)[0].get("data_status") != "planned"
                               and a not in imported}
    not_in_master = imported - master_ids

    print("📋 awards_master 照合結果")
    print(f"  master登録数: {len(master_ids)}")
    print(f"  実インポート済み賞: {sorted(imported)}")
    if not_in_master:
        print(f"  ⚠️  master未登録の賞: {not_in_master}")
    else:
        print("  ✅ 全インポート済み賞がmasterに登録済み")

    print("\n賞別 weight:")
    for r in sorted(master, key=lambda x: -int(x.get("weight", 0))):
        status = "✅ imported" if r["award_id"] in imported else f"  ({r.get('data_status', '-')})"
        print(f"  {r['award_id']:5s}  weight={r['weight']:>3s}  {r['award_type']:15s}  {status}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--similarity",      action="store_true")
    parser.add_argument("--graph",           action="store_true")
    parser.add_argument("--validate-master", action="store_true")
    args = parser.parse_args()

    if args.similarity:
        _build_similarity()
    if args.graph:
        _build_graph()
    if args.validate_master:
        _validate_master()
    if not (args.similarity or args.graph or args.validate_master):
        parser.print_help()


if __name__ == "__main__":
    main()

"""
PLAM サービス層 — CSV → JSON変換（Cytoscape.js / API向け）
"""
from __future__ import annotations
import csv
from functools import lru_cache
from pathlib import Path

PLAM_DIR = Path(__file__).parent.parent / "data" / "plam"

CLUSTER_COLORS = {
    "mystery": "#e85d04",
    "literary": "#6a4c93",
    "sf":       "#0066cc",
    "horror":   "#2a9d8f",
    "career":   "#888888",
    "debut":    "#e9c46a",
    "unknown":  "#cccccc",
}


def _read(filename: str) -> list[dict]:
    path = PLAM_DIR / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


@lru_cache(maxsize=1)
def _awards_master() -> dict[str, dict]:
    return {r["award_id"]: r for r in _read("awards_master.csv")}


@lru_cache(maxsize=1)
def _cluster_map() -> dict[str, str]:
    """award_id → cluster_id"""
    result: dict[str, str] = {}
    for r in _read("cluster_summary.csv"):
        result[r["award_id"]] = r["cluster_id"]
    return result


def get_award_network() -> dict:
    """Cytoscape.js 向けネットワークデータ（ノード＋エッジ＋クラスタ凡例）を返す。"""
    master    = _awards_master()
    cluster_m = _cluster_map()
    edges_raw = _read("graph_data.csv")

    # ノード生成（awards_master.csv の全賞）
    nodes = []
    for aid, info in master.items():
        if info.get("data_status") == "planned":
            continue
        cluster = cluster_m.get(aid, "unknown")
        nodes.append({
            "id":         aid,
            "label":      info.get("award_name", aid),
            "award_type": info.get("award_type", ""),
            "cluster":    cluster,
            "color":      CLUSTER_COLORS.get(cluster, "#ccc"),
            "weight":     int(info.get("weight", 70)),
            "founded":    info.get("founded", ""),
        })

    # エッジ生成（graph_data.csv の Jaccard > 0 のペア）
    edges = []
    for r in edges_raw:
        jaccard = float(r.get("weight", 0))
        edges.append({
            "source":        r["source"],
            "target":        r["target"],
            "jaccard":       jaccard,
            "shared_works":  int(r.get("shared_works", 0)),
            "shared_titles": r.get("shared_titles", ""),
        })

    # クラスタ凡例
    seen: set[str] = set()
    clusters = []
    for n in nodes:
        cid = n["cluster"]
        if cid not in seen:
            seen.add(cid)
            clusters.append({"id": cid, "color": n["color"]})

    return {"nodes": nodes, "edges": edges, "clusters": clusters}


def get_bridge_works(limit: int = 50) -> list[dict]:
    """bridge_works.csv から cross_cluster 作品を優先して返す。"""
    rows = _read("bridge_works.csv")
    cross = [r for r in rows if r.get("bridge_type") == "cross_cluster"]
    intra = [r for r in rows if r.get("bridge_type") == "intra_cluster"]
    result = cross + intra
    return result[:limit]


def invalidate_cache() -> None:
    _awards_master.cache_clear()
    _cluster_map.cache_clear()

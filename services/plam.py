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


import unicodedata
import re as _re


def _normalize(s: str) -> str:
    """タイトル照合用正規化: NFKC変換 + 小文字 + 空白除去"""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = _re.sub(r"[\s　]+", "", s)  # 全角・半角スペース除去
    return s


@lru_cache(maxsize=1)
def _works_index() -> dict[str, dict]:
    """正規化タイトル → works行 のインデックス（NFKC正規化済み）"""
    result: dict[str, dict] = {}
    for r in _read("works.csv"):
        t = r.get("canonical_title", "")
        if t:
            result[_normalize(t)] = r
    return result


@lru_cache(maxsize=1)
def _history_by_work() -> dict[str, list[dict]]:
    """work_id → award_history行リスト"""
    result: dict[str, list[dict]] = {}
    for r in _read("award_history.csv"):
        wid = r.get("work_id", "")
        result.setdefault(wid, []).append(r)
    return result


@lru_cache(maxsize=1)
def _bridge_set() -> set[str]:
    """cross_cluster bridge work の work_id セット"""
    return {r["work_id"] for r in _read("bridge_works.csv") if r.get("bridge_type") == "cross_cluster"}


@lru_cache(maxsize=1)
def _jaccard_map() -> dict[tuple[str, str], float]:
    """(award_a, award_b) → jaccard係数（順不同）"""
    result: dict[tuple[str, str], float] = {}
    for r in _read("award_similarity.csv"):
        a, b = r.get("award_a", ""), r.get("award_b", "")
        j = float(r.get("jaccard", 0) or 0)
        if a and b:
            result[(a, b)] = j
            result[(b, a)] = j
    return result


def get_book_plam_info(title: str, author: str = "") -> dict | None:
    """書籍タイトルからPLAM情報を返す。見つからなければNone。"""
    if not title:
        return None

    works = _works_index()
    master = _awards_master()
    cluster_m = _cluster_map()
    history = _history_by_work()
    bridges = _bridge_set()

    key = _normalize(title)
    work = works.get(key)

    # 完全一致なし → 前方一致（短いキーが長いキーの先頭と一致）で再試行
    if not work and len(key) >= 2:
        for k, v in works.items():
            if k.startswith(key) or key.startswith(k):
                work = v
                break

    if not work:
        return None

    wid = work["work_id"]
    rows = history.get(wid, [])
    awards_info = []
    clusters_seen: set[str] = set()

    for r in rows:
        if r.get("status") not in ("awarded", "co_winner"):
            continue
        aid = r.get("award_id", "")
        info = master.get(aid, {})
        cluster = cluster_m.get(aid, "unknown")
        clusters_seen.add(cluster)
        awards_info.append({
            "award_id":   aid,
            "award_name": info.get("award_name", aid),
            "award_year": r.get("award_year", ""),
            "award_no":   r.get("award_no", ""),
            "cluster":    cluster,
            "color":      CLUSTER_COLORS.get(cluster, "#ccc"),
            "weight":     int(info.get("weight", 70)),
        })

    if not awards_info:
        return None

    # 年代順（award_year昇順）。同年はweight降順
    awards_info.sort(key=lambda x: (x["award_year"] or "9999", -x["weight"]))

    return {
        "work_id":    wid,
        "title":      work.get("canonical_title", title),
        "author":     work.get("author", ""),
        "awards":     awards_info,
        "clusters":   [
            {"id": c, "color": CLUSTER_COLORS.get(c, "#ccc")}
            for c in sorted(clusters_seen)
        ],
        "is_bridge":  wid in bridges,
    }


def _plam_score(
    my_awards: set[str],
    my_clusters: set[str],
    w_awards: set[str],
    is_bridge: bool,
    jaccard_m: dict[tuple[str, str], float],
) -> tuple[float, set[str], float]:
    """推薦スコアと内訳を返す。(score, shared_awards, max_jaccard)"""
    shared = my_awards & w_awards
    w_clusters = {_cluster_map().get(a, "unknown") for a in w_awards}
    cluster_bonus = len(my_clusters & w_clusters)

    # Jaccardボーナス: 共有賞ペア間の最大Jaccard
    max_j = 0.0
    for ma in my_awards:
        for wa in w_awards:
            j = jaccard_m.get((ma, wa), 0.0)
            if j > max_j:
                max_j = j

    score = (
        len(shared) * 5
        + (3 if is_bridge else 0)
        + cluster_bonus * 2
        + max_j * 100
    )
    return score, shared, max_j


def _build_reason(
    shared_awards: set[str],
    is_bridge: bool,
    my_clusters: set[str],
    w_clusters: set[str],
) -> str:
    """推薦理由テキストを生成する。"""
    master = _awards_master()
    parts: list[str] = []

    if shared_awards:
        names = [master.get(a, {}).get("award_name", a) for a in sorted(shared_awards)]
        parts.append(f"{'・'.join(names)}の評価軸が共通")
    if is_bridge:
        parts.append("クラスタ横断のBridge Work")
    cross = my_clusters & w_clusters - {"unknown"}
    if cross and not shared_awards:
        parts.append(f"同じ{list(cross)[0]}クラスタ")

    return "・".join(parts) if parts else ""


def get_related_works(work_id: str, limit: int = 6) -> list[dict]:
    """PLAMネットワークを使って関連作品を返す（Jaccard補正スコアリング付き）。"""
    from database import get_con
    import sqlite3

    history = _history_by_work()
    cluster_m = _cluster_map()
    master = _awards_master()
    bridges = _bridge_set()
    jaccard_m = _jaccard_map()

    # 対象作品の賞セット・クラスタセット取得
    my_rows = history.get(work_id, [])
    my_awards: set[str] = {
        r["award_id"] for r in my_rows
        if r.get("status") in ("awarded", "co_winner")
    }
    my_clusters: set[str] = {cluster_m.get(a, "unknown") for a in my_awards}

    if not my_awards:
        return []

    # 全work_idのスコアを計算（自作品除く）
    scored: list[tuple[float, str, dict]] = []
    for wid, rows in history.items():
        if wid == work_id:
            continue
        w_awards = {r["award_id"] for r in rows if r.get("status") in ("awarded", "co_winner")}
        if not (my_awards & w_awards):
            continue
        is_bridge = wid in bridges
        score, shared, max_j = _plam_score(my_awards, my_clusters, w_awards, is_bridge, jaccard_m)
        w_clusters = {cluster_m.get(a, "unknown") for a in w_awards}
        reason = _build_reason(shared, is_bridge, my_clusters, w_clusters)
        scored.append((score, wid, {
            "shared_count": len(shared),
            "is_bridge":    is_bridge,
            "max_jaccard":  round(max_j, 4),
            "reason":       reason,
        }))

    scored.sort(key=lambda x: -x[0])

    # works.csv から作品情報を取得
    wid_to_work: dict[str, dict] = {r["work_id"]: r for r in _read("works.csv")}

    # genre_books との照合（タイトル正規化）
    try:
        con = get_con()
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT isbn, title, author FROM genre_books")
        db_books = {_normalize(r["title"]): dict(r) for r in cur.fetchall()}
        con.close()
    except Exception:
        db_books = {}

    result = []
    for score, wid, meta in scored:
        if len(result) >= limit:
            break
        work = wid_to_work.get(wid)
        if not work:
            continue

        title = work.get("canonical_title", "")
        author = work.get("author", "")
        db_match = db_books.get(_normalize(title))

        # top_award: 最大weightの賞
        w_rows = [r for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")]
        if not w_rows:
            continue
        top_aid = max(w_rows, key=lambda r: int(master.get(r["award_id"], {}).get("weight", 0) or 0))["award_id"]
        cluster = cluster_m.get(top_aid, "unknown")

        result.append({
            "work_id":     wid,
            "title":       title,
            "author":      author,
            "isbn":        db_match["isbn"] if db_match else None,
            "in_library":  db_match is not None,
            "top_award":   master.get(top_aid, {}).get("award_name", top_aid),
            "cluster":     cluster,
            "color":       CLUSTER_COLORS.get(cluster, "#ccc"),
            "score":       round(score, 2),
            "shared_count": meta["shared_count"],
            "is_bridge":   meta["is_bridge"],
            "reason":      meta["reason"],
        })

    return result


def invalidate_cache() -> None:
    _awards_master.cache_clear()
    _cluster_map.cache_clear()
    _works_index.cache_clear()
    _history_by_work.cache_clear()
    _bridge_set.cache_clear()
    _jaccard_map.cache_clear()

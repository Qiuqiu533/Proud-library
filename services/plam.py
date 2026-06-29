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
    """推薦理由テキストを生成する（司書の言葉を意識した自然な日本語）。"""
    master = _awards_master()

    if shared_awards:
        names = sorted(
            [master.get(a, {}).get("award_name", a) for a in shared_awards],
            key=lambda n: -int(master.get(
                next((a for a in shared_awards if master.get(a, {}).get("award_name") == n), ""),
                {}
            ).get("weight", 0) or 0),
        )
        if len(names) == 1:
            base = f"「{names[0]}」の評価傾向が近い作品です。"
        else:
            listed = "」と「".join(names)
            base = f"「{listed}」の両方で高く評価された作品群に近い位置付けです。"
        if is_bridge:
            return base + " クラスタを横断するBridge Workでもあります。"
        return base

    if is_bridge:
        cross = (my_clusters & w_clusters) - {"unknown"}
        if cross:
            label = "・".join(sorted(cross))
            return f"{label}クラスタを横断する、評価軸の広いBridge Workです。"
        return "複数のジャンルにまたがるBridge Workです。"

    cross = (my_clusters & w_clusters) - {"unknown"}
    if cross:
        return f"同じ{list(cross)[0]}クラスタで評価された作品です。"

    return ""


def get_related_works(work_id: str, limit: int = 6) -> list[dict]:
    """PLAMネットワークを使って関連作品を返す（Jaccard補正スコアリング付き）。"""
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
        from database import get_con, fetchall as db_fetchall
        con = get_con()
        rows = db_fetchall(con, "SELECT isbn, title, author FROM genre_books")
        db_books = {_normalize(r["title"]): r for r in rows}
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


def get_my_plam(room: str) -> dict | None:
    """住民の読了履歴からPLAMプロフィールを生成する。

    Returns: {
        matched: int,          # PLAM照合できた作品数
        total: int,            # 読了履歴総数
        clusters: [            # クラスタ別集計（割合降順）
          {id, name, color, count, pct, top_award}
        ],
        top_works: [           # 照合できたPLAM作品（代表5件）
          {work_id, title, author, awards}
        ],
        profile_text: str,     # 自然文プロフィール
    }
    """
    # 読了履歴取得
    try:
        from database import get_con, fetchall as db_fetchall
        con = get_con()
        timeline_rows = db_fetchall(
            con,
            "SELECT title, author, status, created_at FROM reading_timeline WHERE room=? ORDER BY created_at DESC",
            (room,),
        )
        con.close()
    except Exception:
        return None

    if not timeline_rows:
        return None

    total = len(timeline_rows)
    works_idx = _works_index()
    history = _history_by_work()
    cluster_m = _cluster_map()
    master = _awards_master()

    # STEP1: タイトル照合 → work_id
    cluster_counter: dict[str, int] = {}
    top_works: list[dict] = []
    matched_wids: set[str] = set()
    all_my_awards: set[str] = set()  # 読了作品の全受賞賞IDを収集

    for row in timeline_rows:
        title = row.get("title", "")
        if not title:
            continue
        key = _normalize(title)
        work = works_idx.get(key)
        if not work:
            # 前方一致フォールバック（2文字以上）
            if len(key) >= 2:
                for k, v in works_idx.items():
                    if k.startswith(key) or key.startswith(k):
                        work = v
                        break
        if not work:
            continue

        wid = work["work_id"]
        if wid in matched_wids:
            continue
        matched_wids.add(wid)

        # STEP2: クラスタ集計
        w_rows = [r for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")]
        award_ids = {r["award_id"] for r in w_rows}
        all_my_awards |= award_ids
        clusters = {cluster_m.get(a, "unknown") for a in award_ids} - {"unknown"}
        for c in clusters:
            cluster_counter[c] = cluster_counter.get(c, 0) + 1

        # top_works（最大5件、award情報付き）
        if len(top_works) < 5:
            awards_summary = sorted(
                [master.get(aid, {}).get("award_name", aid) for aid in award_ids if aid in master],
                key=lambda n: -int(master.get(
                    next((a for a in award_ids if master.get(a, {}).get("award_name") == n), ""),
                    {}
                ).get("weight", 0) or 0),
            )[:2]
            top_works.append({
                "work_id": wid,
                "title":   work.get("canonical_title", title),
                "author":  work.get("author", ""),
                "awards":  awards_summary,
            })

    matched = len(matched_wids)
    if matched == 0:
        return None

    # STEP3: クラスタ割合計算
    CLUSTER_NAMES = {
        "mystery": "ミステリ",
        "literary": "文学",
        "sf": "SF",
        "horror": "ホラー",
        "career": "キャリア",
        "debut": "デビュー",
    }
    total_cluster_votes = sum(cluster_counter.values()) or 1
    clusters_sorted = sorted(cluster_counter.items(), key=lambda x: -x[1])
    clusters_out = []
    for cid, cnt in clusters_sorted:
        # そのクラスタで最も多く受賞している賞名を取得
        award_counts: dict[str, int] = {}
        for wid in matched_wids:
            for r in history.get(wid, []):
                if r.get("status") not in ("awarded", "co_winner"):
                    continue
                aid = r["award_id"]
                if cluster_m.get(aid) == cid:
                    award_counts[aid] = award_counts.get(aid, 0) + 1
        top_aid = max(award_counts, key=lambda a: award_counts[a]) if award_counts else ""
        top_award_name = master.get(top_aid, {}).get("award_name", "") if top_aid else ""

        clusters_out.append({
            "id":        cid,
            "name":      CLUSTER_NAMES.get(cid, cid),
            "color":     CLUSTER_COLORS.get(cid, "#ccc"),
            "count":     cnt,
            "pct":       round(cnt / total_cluster_votes * 100),
            "top_award": top_award_name,
        })

    # STEP7: My PLAMスコア（19-D強化版）— bridge_centralityを先に計算
    plam_score = _calc_plam_score(matched_wids, clusters_out, all_my_awards)
    bridge_centrality = plam_score.get("bridge_centrality", 0.0)

    # STEP4: 読書タイプ診断（19-D: bridge_centrality渡し）
    reader_type = _diagnose_reader_type(clusters_out, bridge_centrality=bridge_centrality)

    # STEP5: 自然文プロフィール生成
    profile_text = _build_profile_text(clusters_out, matched, total, reader_type)

    # STEP6: 次に読むべき3冊の推薦
    next_reads = _recommend_next_reads(matched_wids, all_my_awards, clusters_out, limit=3)

    # STEP8: 年別読書推移
    yearly_trend = _calc_yearly_trend(timeline_rows, works_idx, history, cluster_m)

    # STEP8b: Phase 20-B クラスタ遷移タイムライン
    cluster_timeline = _calc_cluster_timeline(timeline_rows, works_idx, history, cluster_m)

    # STEP9: チャレンジ提案
    challenges = _build_challenges(clusters_out, matched_wids, all_my_awards)

    return {
        "matched":          matched,
        "total":            total,
        "clusters":         clusters_out,
        "top_works":        top_works,
        "profile_text":     profile_text,
        "reader_type":      reader_type,
        "next_reads":       next_reads,
        "plam_score":       plam_score,
        "yearly_trend":     yearly_trend,
        "cluster_timeline": cluster_timeline,
        "challenges":       challenges,
    }


_READER_TYPES = {
    # (dominant_cluster, has_bridge, diversity) → (label, description)
    # diversity: 1=single cluster, 2=two clusters, 3+=multi
}

def _diagnose_reader_type(clusters: list[dict], bridge_centrality: float = 0.0) -> dict:
    """読書タイプをgraphベースで診断する（Phase 19-D強化版）。

    19-Dの変更点:
    - bridge_centrality（0〜1）を第三の軸として追加
    - high bridge（>0.5）は「接続型」として優先判定
    - stability低クラスタ（horror/sf）の読者を「希少探索型」として評価
    """
    if not clusters:
        return {"label": "分析中", "description": "", "graph_role": "unknown"}

    from services.plam_calibration import get_cluster_stability
    stability = get_cluster_stability()

    top = clusters[0]
    diversity = len(clusters)
    top_pct = top["pct"]
    top_id = top["id"]

    # ① Bridge中心型（bridge_centrality >= 0.5 かつ 複数クラスタ）
    if bridge_centrality >= 0.5 and diversity >= 2:
        t = (
            "ネットワーク中心型",
            "文学賞のジャンル境界を越えて読む「Bridge読者」です。"
            "複数のクラスタを高精度に横断しており、PLAMネットワークの中心に近い読書傾向です。",
            "bridge_hub",
        )
    # ② 希少クラスタ専門型（stability < 0.7 かつ 70%以上）
    elif top_pct >= 70 and stability.get(top_id, 1.0) < 0.7:
        rare_names = {
            "horror": ("ホラー深淵型", "日本ホラー小説大賞など、データが希少な領域を深く探求する希少読書家です。"),
            "sf":     ("SF希少探索型", "日本SF大賞など、小規模ながら独自世界を持つSF領域の専門読者です。"),
            "career": ("作家軌跡型",   "吉川英治賞など、作家の長期キャリアに注目する希少な読書スタイルです。"),
        }
        base = rare_names.get(top_id, ("希少領域型", "PLAMの希少クラスタを深く読む独自の読書家です。"))
        t = (*base, "rare_specialist")
    # ③ 単一クラスタ深掘り型
    elif diversity == 1 or top_pct >= 70:
        types = {
            "mystery":  ("ミステリ探究型", "本格ミステリや推理小説を深く読み込むタイプです。"),
            "literary": ("文学深読み型",   "芥川賞・直木賞などの純文学・文芸作品を好むタイプです。"),
            "sf":       ("SF開拓型",       "日本SF大賞など、SF作品に特化した読書をするタイプです。"),
            "horror":   ("ホラー沈潜型",   "ホラー小説の独自世界を深く探求するタイプです。"),
            "career":   ("作家キャリア型", "吉川英治賞など、作家の長期的評価に注目するタイプです。"),
        }
        base = types.get(top_id, ("独自探索型", "独自の読書スタイルを持つタイプです。"))
        t = (*base, "single_cluster")
    # ④ 2クラスタ横断型
    elif diversity == 2:
        second = clusters[1]
        pair = frozenset({top_id, second["id"]})
        if pair == frozenset({"mystery", "literary"}):
            t = ("文学×ミステリ横断型",
                 "文学性とミステリ性の両方を高く評価する、Bridge Work的な読書傾向です。",
                 "cross_cluster")
        elif "sf" in pair:
            t = ("SF×文芸融合型",
                 "SFと文芸の境界を越えた作品を好む、知的好奇心旺盛なタイプです。",
                 "cross_cluster")
        elif "horror" in pair:
            t = ("ホラー×文芸型",
                 "ホラーと文芸の両方に精通した、独自の感性を持つ読者です。",
                 "cross_cluster")
        else:
            t = ("クロスジャンル型",
                 "複数のジャンルを横断する幅広い読書傾向のタイプです。",
                 "cross_cluster")
    # ⑤ 全クラスタ網羅型
    else:
        t = ("バランス読書型",
             "特定のジャンルに偏らず、文学賞全般にわたって幅広く読むタイプです。",
             "balanced")

    return {"label": t[0], "description": t[1], "graph_role": t[2]}


def _recommend_next_reads(
    read_wids: set[str],
    my_awards: set[str],
    clusters: list[dict],
    limit: int = 3,
) -> list[dict]:
    """読了作品から、まだ読んでいないPLAM作品を推薦する。

    優先: Bridge Work > 未経験クラスタ > 既存クラスタの高スコア作品
    """
    history = _history_by_work()
    cluster_m = _cluster_map()
    master = _awards_master()
    bridges = _bridge_set()
    jaccard_m = _jaccard_map()

    my_clusters = {cluster_m.get(a, "unknown") for a in my_awards}
    unread_clusters = {"mystery", "literary", "sf", "horror", "career"} - my_clusters

    # genre_books照合
    try:
        from database import get_con, fetchall as db_fetchall
        con = get_con()
        rows = db_fetchall(con, "SELECT isbn, title FROM genre_books")
        db_books = {_normalize(r["title"]): r["isbn"] for r in rows}
        con.close()
    except Exception:
        db_books = {}

    wid_to_work = {r["work_id"]: r for r in _read("works.csv")}
    candidates: list[tuple[float, str]] = []

    for wid, rows in history.items():
        if wid in read_wids:
            continue
        w_awards = {r["award_id"] for r in rows if r.get("status") in ("awarded", "co_winner")}
        if not w_awards:
            continue

        is_bridge = wid in bridges
        score, shared, max_j = _plam_score(my_awards, my_clusters, w_awards, is_bridge, jaccard_m)

        # 未経験クラスタへのボーナス
        w_clusters = {cluster_m.get(a, "unknown") for a in w_awards}
        expansion_bonus = 5 if w_clusters & unread_clusters else 0
        candidates.append((score + expansion_bonus, wid))

    candidates.sort(key=lambda x: -x[0])

    result = []
    for score, wid in candidates:
        if len(result) >= limit:
            break
        work = wid_to_work.get(wid)
        if not work:
            continue

        title = work.get("canonical_title", "")
        w_rows = [r for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")]
        top_aid = max(w_rows, key=lambda r: int(master.get(r["award_id"], {}).get("weight", 0) or 0))["award_id"]
        w_clusters = {cluster_m.get(r["award_id"], "unknown") for r in w_rows}
        expansion = bool(w_clusters & unread_clusters)

        # 推薦理由
        shared_awards = my_awards & {r["award_id"] for r in w_rows}
        reason = _build_reason(shared_awards, wid in bridges, my_clusters, w_clusters)
        if expansion:
            exp_name = {"mystery": "ミステリ", "literary": "文学", "sf": "SF", "horror": "ホラー"}.get(
                (w_clusters & unread_clusters).pop(), "新ジャンル"
            )
            reason = f"{exp_name}クラスタへの入口となる作品です。" + (" " + reason if reason else "")

        result.append({
            "work_id":    wid,
            "title":      title,
            "author":     work.get("author", ""),
            "isbn":       db_books.get(_normalize(title)),
            "in_library": _normalize(title) in db_books,
            "top_award":  master.get(top_aid, {}).get("award_name", top_aid),
            "color":      CLUSTER_COLORS.get(cluster_m.get(top_aid, "unknown"), "#ccc"),
            "is_bridge":  wid in bridges,
            "expansion":  expansion,
            "reason":     reason,
        })

    return result


def _build_profile_text(clusters: list[dict], matched: int, total: int, reader_type: dict | None = None) -> str:
    """My PLAMの自然文プロフィールを生成する。"""
    if not clusters:
        return ""

    top = clusters[0]
    lines: list[str] = []

    # 読書タイプの説明から始める
    if reader_type and reader_type.get("description"):
        lines.append(reader_type["description"])
    elif top["top_award"]:
        lines.append(f"「{top['top_award']}」の受賞作品を多く読まれています。")
    else:
        lines.append(f"{top['name']}系の作品を多く読まれています。")

    # 2番目のクラスタ言及
    if len(clusters) >= 2:
        second = clusters[1]
        lines.append(
            f"{second['name']}作品も{second['pct']}%を占めており、幅広い読書傾向が見られます。"
        )

    # 未照合作品へのコメント
    unmatched = total - matched
    if unmatched > 0 and total >= 5:
        lines.append(f"（読了{total}冊中{matched}冊が文学賞受賞作です）")

    return " ".join(lines)


def _calc_plam_score(
    matched_wids: set[str],
    clusters: list[dict],
    all_awards: set[str],
) -> dict:
    """My PLAMスコアを100点満点で計算する（Phase 19-D強化版）。

    軸:
    - 読書の広がり:        到達クラスタ数 / 5 × 30点
    - 受賞作読了数:        min(matched, 50) / 50 × 25点
    - Bridge参加度:        bridge_centrality × 20点  ← stability重み付き（19-D新）
    - クラスタバランス:    シャノンエントロピー × 10点
    - ユーザーPLAM一致度:  user_profile_score × 15点 ← 19-D新
    """
    import math
    from services.plam_calibration import get_cluster_stability, get_bridge_work_ids

    stability = get_cluster_stability()
    bridge_ids_19c = get_bridge_work_ids()  # 19-C検出ブリッジ（award_historyベース）
    bridges_legacy = _bridge_set()          # bridge_works.csvベース（既存）
    all_bridges = bridge_ids_19c | bridges_legacy

    n_clusters = len(clusters)
    matched = len(matched_wids)

    # 1. 広がり点（30点）
    spread = round(n_clusters / 5 * 30)

    # 2. 受賞作読了点（25点）
    award_score = round(min(matched, 50) / 50 * 25)

    # 3. Bridge参加度 centrality（20点）—— stability重み付き
    # bridge作品ごとに所属クラスタのstabilityを乗じた重みで集計
    bridge_centrality_sum = 0.0
    cluster_m = _cluster_map()
    history = _history_by_work()
    for wid in matched_wids & all_bridges:
        w_awards = {r["award_id"] for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")}
        w_clusters = {cluster_m.get(a, "unknown") for a in w_awards} - {"unknown"}
        w_stab = max((stability.get(c, 0.5) for c in w_clusters), default=0.5)
        bridge_centrality_sum += w_stab
    max_bridge_centrality = sum(
        max((stability.get(c, 0.5) for c in {cluster_m.get(a, "unknown") for a in
             {r["award_id"] for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")}} - {"unknown"}), default=0.5)
        for wid in all_bridges
    ) or 1.0
    bridge_score = round(min(bridge_centrality_sum / max_bridge_centrality, 1.0) * 20)

    # 4. バランス点（10点）
    total_votes = sum(c["count"] for c in clusters)
    if total_votes > 0 and n_clusters > 1:
        entropy = -sum(
            (c["count"] / total_votes) * math.log2(c["count"] / total_votes)
            for c in clusters if c["count"] > 0
        )
        max_entropy = math.log2(n_clusters)
        balance = round(entropy / max_entropy * 10) if max_entropy > 0 else 0
    else:
        balance = 0

    # 5. ユーザーPLAM一致度（15点）—— 19-D新
    # user_profile_score: 読了作品の19-C final_score平均
    from services.plam_calibration import calibrate_sim, compute_final_score
    from difflib import SequenceMatcher
    cal_stats_ref = None  # キャッシュ済みなのでNoneでもget_calibration_stats()が使われる
    profile_scores = []
    works_idx = _works_index()
    for wid in matched_wids:
        work = next((v for v in works_idx.values() if v.get("work_id") == wid), None)
        if not work:
            continue
        title = work.get("canonical_title", "")
        w_awards = {r["award_id"] for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")}
        cluster_id = next(iter({cluster_m.get(a) for a in w_awards if cluster_m.get(a)}), None)
        # 完全一致なのでbase=1.0として計算（読了済み=確実に一致）
        score = compute_final_score(1.0, cluster_id, plam_work_id=wid,
                                    stability=stability, bridge_ids=all_bridges)
        profile_scores.append(score)

    user_profile = sum(profile_scores) / len(profile_scores) if profile_scores else 0.0
    profile_score = round(user_profile * 15)

    total_score = spread + award_score + bridge_score + balance + profile_score

    return {
        "total":          total_score,
        "spread":         spread,
        "award_score":    award_score,
        "bridge_score":   bridge_score,
        "balance":        balance,
        "profile_score":  profile_score,
        "bridge_read":    len(matched_wids & all_bridges),
        "n_clusters":     n_clusters,
        "user_profile":   round(user_profile, 3),
        "bridge_centrality": round(bridge_centrality_sum / max_bridge_centrality, 3),
    }


def _calc_yearly_trend(
    timeline_rows: list[dict],
    works_idx: dict,
    history: dict,
    cluster_m: dict,
) -> list[dict]:
    """年別のクラスタ分布推移を計算する。直近3年分。"""
    from datetime import datetime

    year_data: dict[str, dict[str, int]] = {}
    for row in timeline_rows:
        ts = row.get("created_at", "")
        if not ts:
            continue
        try:
            year = str(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).year)
        except Exception:
            year = str(ts)[:4]
        if not year.isdigit() or int(year) < 2020:
            continue

        title = row.get("title", "")
        if not title:
            continue
        key = _normalize(title)
        work = works_idx.get(key)
        if not work:
            continue

        wid = work["work_id"]
        w_rows = [r for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")]
        clusters = {cluster_m.get(r["award_id"], "unknown") for r in w_rows} - {"unknown"}
        for c in clusters:
            year_data.setdefault(year, {})
            year_data[year][c] = year_data[year].get(c, 0) + 1

    if not year_data:
        return []

    # 直近3年のみ返す
    years = sorted(year_data.keys())[-3:]
    ALL_CLUSTERS = ["mystery", "literary", "sf", "horror", "career"]
    result = []
    for y in years:
        counts = year_data[y]
        total = sum(counts.values()) or 1
        result.append({
            "year": y,
            "clusters": {
                c: round(counts.get(c, 0) / total * 100)
                for c in ALL_CLUSTERS
            },
            "total_matched": sum(counts.values()),
        })
    return result


def _calc_cluster_timeline(
    timeline_rows: list[dict],
    works_idx: dict,
    history: dict,
    cluster_m: dict,
) -> dict:
    """Phase 20-B: クラスタ遷移タイムラインを生成する。

    Returns: {
        "quarters": [{"period": "2023-Q1", "dominant": "mystery", "counts": {...}, "works": [...]}],
        "transition_matrix": {"mystery->literary": 3, ...},
        "migration_path": ["mystery", "literary", "sf"],
        "drift_score": float,  # 0〜1: 高いほど多様なクラスタを横断
    }
    """
    from datetime import datetime

    # クォーター別にcluster集計
    quarter_data: dict[str, dict] = {}  # "2023-Q1" -> {cluster -> [{title, work_id}]}

    for row in timeline_rows:
        ts = row.get("created_at", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            period = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
        except Exception:
            continue

        title = row.get("title", "")
        if not title:
            continue
        key = _normalize(title)
        work = works_idx.get(key)
        if not work:
            # 前方一致フォールバック
            if len(key) >= 2:
                for k, v in works_idx.items():
                    if k.startswith(key) or key.startswith(k):
                        work = v
                        break
        if not work:
            continue

        wid = work["work_id"]
        w_rows = [r for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")]
        clusters = {cluster_m.get(r["award_id"], "unknown") for r in w_rows} - {"unknown"}
        if not clusters:
            continue

        quarter_data.setdefault(period, {})
        for c in clusters:
            quarter_data[period].setdefault(c, [])
            quarter_data[period][c].append({
                "work_id": wid,
                "title": work.get("canonical_title", title),
            })

    if not quarter_data:
        return {"quarters": [], "transition_matrix": {}, "migration_path": [], "drift_score": 0.0}

    # クォーター順にソート（直近8四半期）
    sorted_periods = sorted(quarter_data.keys())[-8:]
    ALL_CLUSTERS = ["mystery", "literary", "sf", "horror", "career"]

    quarters = []
    dominant_seq: list[str] = []
    for period in sorted_periods:
        counts = {c: len(quarter_data[period].get(c, [])) for c in ALL_CLUSTERS}
        dominant = max(counts, key=lambda c: counts[c]) if any(counts.values()) else "unknown"
        works_sample = []
        for c in ALL_CLUSTERS:
            for w in quarter_data[period].get(c, [])[:2]:
                works_sample.append({**w, "cluster": c})
        quarters.append({
            "period": period,
            "dominant": dominant,
            "counts": counts,
            "works": works_sample[:4],
        })
        dominant_seq.append(dominant)

    # 遷移行列: dominant cluster の連続遷移を集計
    transition_matrix: dict[str, int] = {}
    for i in range(len(dominant_seq) - 1):
        a, b = dominant_seq[i], dominant_seq[i + 1]
        if a != b:
            key = f"{a}->{b}"
            transition_matrix[key] = transition_matrix.get(key, 0) + 1

    # migration path: 重複を除いた遷移シーケンス
    migration_path: list[str] = []
    for c in dominant_seq:
        if not migration_path or migration_path[-1] != c:
            migration_path.append(c)

    # drift_score: ユニーク遷移数 / 可能な最大遷移数
    n_transitions = len(dominant_seq) - 1
    n_unique = len(set(transition_matrix.keys()))
    drift_score = round(n_unique / max(n_transitions, 1), 3) if n_transitions > 0 else 0.0

    return {
        "quarters": quarters,
        "transition_matrix": transition_matrix,
        "migration_path": migration_path,
        "drift_score": drift_score,
    }


def get_plam_embedding(room: str | None = None) -> dict:
    """Phase 20-C: 作品距離マップの2D座標とユーザー位置を返す。

    作品座標の算出:
      - 各クラスタを正五角形の頂点に配置（固定）
      - 単一クラスタ作品 → クラスタ中心 + work_idハッシュベースのジッター
      - Bridge work（複数クラスタ）→ クラスタ中心の加重平均
    ユーザー位置:
      - 読了済み作品座標の単純平均

    Returns: {
        "works": [{work_id, x, y, cluster, title}],
        "user_pos": {x, y} | None,
        "user_works": [work_id, ...],
    }
    """
    import math
    import hashlib

    # クラスタ中心（正五角形、中心(0.5, 0.5)・半径0.38）
    _PENTAGON_ANGLES = {
        "literary": -math.pi / 2,           # 上
        "mystery":  -math.pi / 2 + 2 * math.pi / 5,
        "sf":       -math.pi / 2 + 4 * math.pi / 5,
        "horror":   -math.pi / 2 + 6 * math.pi / 5,
        "career":   -math.pi / 2 + 8 * math.pi / 5,
    }
    _R = 0.38
    CLUSTER_CENTERS: dict[str, tuple[float, float]] = {
        cid: (round(0.5 + _R * math.cos(a), 4), round(0.5 + _R * math.sin(a), 4))
        for cid, a in _PENTAGON_ANGLES.items()
    }

    def _jitter(work_id: str, radius: float = 0.10) -> tuple[float, float]:
        h = int(hashlib.md5(work_id.encode()).hexdigest()[:8], 16)
        angle = (h % 360) * math.pi / 180
        r = (h % 1000) / 1000 * radius
        return (round(r * math.cos(angle), 4), round(r * math.sin(angle), 4))

    cluster_m = _cluster_map()
    works_raw = _read("works.csv")
    history = _history_by_work()

    from services.plam_calibration import get_cluster_stability
    stability = get_cluster_stability()

    # award_books から plam_work_id → isbn の逆引きマップを生成（21-B）
    isbn_by_wid: dict[str, str] = {}
    try:
        from database import get_con, fetchall as db_fetchall
        con = get_con()
        rows = db_fetchall(
            con,
            "SELECT plam_work_id, isbn FROM award_books WHERE plam_work_id IS NOT NULL AND isbn IS NOT NULL AND isbn != ''"
        )
        for row in rows:
            wid_key = str(row["plam_work_id"])
            isbn_val = str(row["isbn"])
            if wid_key and isbn_val and wid_key not in isbn_by_wid:
                isbn_by_wid[wid_key] = isbn_val
        con.close()
    except Exception:
        pass

    works_out: list[dict] = []
    work_positions: dict[str, tuple[float, float]] = {}

    for w in works_raw:
        wid = w.get("work_id", "")
        if not wid:
            continue
        title = w.get("canonical_title", "")

        # このworkが属するクラスタ（受賞歴から）
        w_rows = [r for r in history.get(wid, []) if r.get("status") in ("awarded", "co_winner")]
        award_ids = {r["award_id"] for r in w_rows}
        clusters = {cluster_m.get(a, "unknown") for a in award_ids} - {"unknown"}

        if not clusters:
            # クラスタ不明: マップ中央付近にジッター
            jx, jy = _jitter(wid, radius=0.08)
            x, y = round(0.5 + jx, 4), round(0.5 + jy, 4)
            primary = "unknown"
        elif len(clusters) == 1:
            primary = list(clusters)[0]
            cx, cy = CLUSTER_CENTERS.get(primary, (0.5, 0.5))
            jx, jy = _jitter(wid, radius=0.12)
            x, y = round(cx + jx, 4), round(cy + jy, 4)
        else:
            # Bridge work: stability重みつき加重平均
            primary = "bridge"
            total_w = sum(stability.get(c, 0.5) for c in clusters)
            x = round(sum(CLUSTER_CENTERS.get(c, (0.5, 0.5))[0] * stability.get(c, 0.5) for c in clusters) / max(total_w, 0.01), 4)
            y = round(sum(CLUSTER_CENTERS.get(c, (0.5, 0.5))[1] * stability.get(c, 0.5) for c in clusters) / max(total_w, 0.01), 4)
            jx, jy = _jitter(wid, radius=0.04)
            x, y = round(x + jx, 4), round(y + jy, 4)

        x = max(0.02, min(0.98, x))
        y = max(0.02, min(0.98, y))

        work_positions[wid] = (x, y)
        entry: dict = {
            "work_id": wid,
            "title":   title,
            "cluster": primary,
            "x":       x,
            "y":       y,
        }
        if wid in isbn_by_wid:
            entry["isbn"] = isbn_by_wid[wid]
        works_out.append(entry)

    # ユーザー位置（roomが指定された場合）
    user_pos = None
    user_wids: list[str] = []

    if room:
        try:
            from database import get_con, fetchall as db_fetchall
            con = get_con()
            rows = db_fetchall(
                con,
                "SELECT title FROM reading_timeline WHERE room=? ORDER BY created_at DESC",
                (room,)
            )
            con.close()

            works_idx = _works_index()
            for row in rows:
                key = _normalize(row.get("title", ""))
                work = works_idx.get(key)
                if not work:
                    if len(key) >= 2:
                        for k, v in works_idx.items():
                            if k.startswith(key) or key.startswith(k):
                                work = v
                                break
                if work:
                    wid = work["work_id"]
                    if wid in work_positions and wid not in user_wids:
                        user_wids.append(wid)

            if user_wids:
                xs = [work_positions[w][0] for w in user_wids]
                ys = [work_positions[w][1] for w in user_wids]
                user_pos = {"x": round(sum(xs) / len(xs), 4), "y": round(sum(ys) / len(ys), 4)}
        except Exception:
            pass

    return {
        "works":       works_out,
        "user_pos":    user_pos,
        "user_works":  user_wids,
        "cluster_centers": {k: {"x": v[0], "y": v[1]} for k, v in CLUSTER_CENTERS.items()},
    }


def _build_challenges(
    clusters: list[dict],
    matched_wids: set[str],
    all_awards: set[str],
) -> list[str]:
    """チャレンジ提案文を生成する（最大3件）。"""
    bridges = _bridge_set()
    cluster_m = _cluster_map()
    history = _history_by_work()

    achieved_clusters = {c["id"] for c in clusters}
    all_clusters = {"mystery", "literary", "sf", "horror", "career"}
    missing_clusters = all_clusters - achieved_clusters
    bridge_read = len(matched_wids & bridges)
    total_bridges = 12

    CLUSTER_NAMES = {
        "mystery": "ミステリ", "literary": "文学", "sf": "SF",
        "horror": "ホラー", "career": "キャリア",
    }

    challenges: list[str] = []

    # 1. クラスタ制覇チャレンジ
    if missing_clusters:
        if len(missing_clusters) == 1:
            m = CLUSTER_NAMES.get(list(missing_clusters)[0], list(missing_clusters)[0])
            challenges.append(f"🎯 {m}クラスタの作品を1冊読むと、全5クラスタ制覇達成です！")
        else:
            names = "・".join(CLUSTER_NAMES.get(c, c) for c in sorted(missing_clusters))
            challenges.append(f"📚 未読クラスタ: {names}。制覇まであと{len(missing_clusters)}クラスタ！")

    # 2. Bridge Workチャレンジ
    remaining_bridges = total_bridges - bridge_read
    if remaining_bridges > 0:
        if bridge_read == 0:
            challenges.append(f"🌉 Bridge Workをまだ読んでいません。クラスタを横断する{total_bridges}冊の特別作品に挑戦してみましょう！")
        elif remaining_bridges <= 3:
            challenges.append(f"🌉 Bridge Workをあと{remaining_bridges}冊で全制覇（{bridge_read}/{total_bridges}冊読了）！")
        else:
            challenges.append(f"🌉 Bridge Workを{bridge_read}冊読了中。残り{remaining_bridges}冊があります。")

    # 3. 少数派クラスタ強化チャレンジ
    if len(clusters) >= 2:
        weakest = min(clusters, key=lambda c: c["pct"])
        if weakest["pct"] <= 15:
            # あと何冊でしきい値超えか試算
            top_count = clusters[0]["count"]
            needed = max(1, int(top_count * 0.25) - weakest["count"] + 1)
            challenges.append(
                f"📈 「{weakest['name']}」作品があと{needed}冊増えると読書バランスが向上します。"
            )

    return challenges[:3]


def invalidate_cache() -> None:
    _awards_master.cache_clear()
    _cluster_map.cache_clear()
    _works_index.cache_clear()
    _history_by_work.cache_clear()
    _bridge_set.cache_clear()
    _jaccard_map.cache_clear()

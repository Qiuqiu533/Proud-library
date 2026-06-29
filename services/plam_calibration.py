"""
PLAM Normalization Layer — title_sim のキャリブレーション

背景分布（同一賞内ランダムペアの類似度）:
  mean ≈ 0.03, std ≈ 0.07, p99 ≈ 0.29

解釈:
  raw_sim が 0.30 を超えるだけで既に p99 に到達する。
  したがって raw_sim=0.85 は「ほぼ確実」だが、
  0.50 と 0.85 の差が「あやふや vs 確実」として見えづらい。

正規化式（per-award）:
  calibrated = clip((raw_sim - mean) / (1.0 - mean), 0, 1)

  これにより:
    raw_sim = mean (≈0.03) → 0.0
    raw_sim = 1.0          → 1.0
    raw_sim = 0.50 (AKU)   → (0.50 - 0.024) / (1 - 0.024) ≈ 0.488
    raw_sim = 0.85 (AKU)   → (0.85 - 0.024) / (1 - 0.024) ≈ 0.847

注意: 全体的な尺度は変わらないが、
      背景ノイズ領域（0〜0.15）が圧縮されて意味のある差分が拡大する。

使い方:
    from services.plam_calibration import calibrate_sim, get_calibration_stats
    stats = get_calibration_stats()           # {award_id: {mean, std, n}}
    cal_score = calibrate_sim(0.87, "AKU", stats)
"""
from __future__ import annotations
import csv
import math
import random
import unicodedata
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

PLAM_DIR = Path(__file__).parent.parent / "data" / "plam"
_SAMPLE_PER_AWARD = 200
_RANDOM_SEED = 42


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower()
    s = re.sub(r"[\s　]+", "", s)
    return s


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@lru_cache(maxsize=1)
def get_calibration_stats() -> dict[str, dict]:
    """賞ごとの背景分布統計を返す（初回のみ計算・以降キャッシュ）。

    Returns:
        {award_id: {"mean": float, "std": float, "n": int}}
    """
    # works読み込み
    works: dict[str, str] = {}
    with open(PLAM_DIR / "works.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("canonical_title", "")
            if t:
                works[row["work_id"]] = _normalize(t)

    # award_history → award別 work_idリスト
    from collections import defaultdict
    award_works: dict[str, list[str]] = defaultdict(list)
    with open(PLAM_DIR / "award_history.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wid = row.get("work_id", "")
            aid = row.get("award_id", "")
            if wid and aid and wid in works:
                award_works[aid].append(wid)

    rng = random.Random(_RANDOM_SEED)
    stats: dict[str, dict] = {}

    for aid, wids in award_works.items():
        titles = [works[w] for w in wids]
        pairs = [(titles[i], titles[j])
                 for i in range(len(titles))
                 for j in range(i + 1, len(titles))]
        sample = rng.sample(pairs, min(len(pairs), _SAMPLE_PER_AWARD))
        sims = [_sim(a, b) for a, b in sample]
        if not sims:
            continue
        mean = sum(sims) / len(sims)
        variance = sum((x - mean) ** 2 for x in sims) / len(sims)
        std = math.sqrt(variance)
        stats[aid] = {"mean": round(mean, 5), "std": round(std, 5), "n": len(sims)}

    # 全体フォールバック統計
    all_means = [v["mean"] for v in stats.values()]
    all_stds  = [v["std"]  for v in stats.values()]
    if all_means:
        global_mean = sum(all_means) / len(all_means)
        global_std  = sum(all_stds)  / len(all_stds)
        stats["__global__"] = {"mean": round(global_mean, 5), "std": round(global_std, 5), "n": -1}

    return stats


def calibrate_sim(raw_sim: float, award_id: str | None = None, stats: dict | None = None) -> float:
    """raw_sim を背景分布で正規化して [0, 1] に変換する。

    式:  calibrated = clip((raw_sim - mean) / (1.0 - mean), 0, 1)

    これにより:
      - 背景ノイズ領域（raw_sim ≈ mean ≈ 0.03）→ 0.0付近
      - 完全一致（raw_sim = 1.0）          → 1.0
      - 0.50付近の「揺れ候補」が [0.48〜0.55] に明確にマッピング
    """
    if stats is None:
        stats = get_calibration_stats()
    s = stats.get(award_id or "", stats.get("__global__", {"mean": 0.03}))
    mean = s["mean"]
    denom = 1.0 - mean
    if denom <= 0:
        return 1.0 if raw_sim >= mean else 0.0
    cal = (raw_sim - mean) / denom
    return max(0.0, min(1.0, cal))


def calibrated_score(
    db_title: str,
    db_author: str,
    db_award: str,
    plam_title: str,
    plam_author: str,
    stats: dict | None = None,
    author_weight: float = 0.10,
    award_bonus: float = 0.05,
    has_award_match: bool = False,
) -> float:
    """キャリブレーション済み信頼スコアを返す。

    raw_title_sim → calibrate_sim → calibrated_title_sim
    final_score = calibrated_title_sim * 0.85 + author_ok + award_bonus
    """
    if stats is None:
        stats = get_calibration_stats()

    dt = _normalize(db_title)
    pt = _normalize(plam_title)
    raw_sim = _sim(dt, pt)

    cal_sim = calibrate_sim(raw_sim, db_award, stats)

    da = _normalize(db_author or "")
    pa = _normalize(plam_author or "")
    author_ok = author_weight if (da and pa and (da == pa or da in pa or pa in da)) else 0.0

    bonus = award_bonus if has_award_match else 0.0

    return min(1.0, cal_sim * 0.85 + author_ok + bonus)


_BRIDGE_BONUS = 0.15      # Bridge Work への加算ボーナス
_CLUSTER_BASE_WEIGHT = 0.85   # stability=0 時の最低クラスタ係数
_CLUSTER_STABILITY_SCALE = 0.15  # stability=1 時の最大追加分

_CLUSTER_MAP: dict[str, str] = {
    "HKM": "mystery", "JRA": "mystery", "KMS": "mystery",
    "RAN": "mystery", "YAM": "mystery",
    "AKU": "literary", "NAO": "literary", "HON": "literary",
    "KIK": "career",
    "JSF": "sf",
    "HOR": "horror",
}

_BASELINE_THRESHOLD = 0.90
_CLUSTER_SENSITIVITY = 2.0  # p99_cal差に乗じるオフセット倍率


@lru_cache(maxsize=1)
def get_cluster_thresholds() -> dict[str, float]:
    """クラスタ別adaptive thresholdを返す。

    算出式:
        cluster_threshold = BASELINE + (cluster_p99_cal - global_p99_cal) * SENSITIVITY

    直感:
        ノイズが高い（p99_cal大）クラスタ → threshold を少し上げる
        ノイズが低い（p99_cal小）クラスタ → threshold を少し下げる
        → 「同じ意味のある違いを見つける難しさ」をクラスタごとに補正

    Returns:
        {cluster_id: threshold, "__global__": baseline}
    """
    from collections import defaultdict

    stats = get_calibration_stats()

    # クラスタ別ワーク収集
    award_works: dict[str, list[str]] = defaultdict(list)
    works_titles: dict[str, str] = {}
    with open(PLAM_DIR / "works.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("canonical_title", "")
            if t:
                works_titles[row["work_id"]] = _normalize(t)

    with open(PLAM_DIR / "award_history.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wid = row.get("work_id", "")
            aid = row.get("award_id", "")
            if wid in works_titles and aid:
                cluster = _CLUSTER_MAP.get(aid, "unknown")
                award_works[cluster].append(wid)

    rng = random.Random(_RANDOM_SEED)
    cluster_p99: dict[str, float] = {}

    for cluster, wids in award_works.items():
        unique = list(set(wids))
        titles = [works_titles[w] for w in unique]
        pairs = [
            (titles[i], titles[j])
            for i in range(len(titles))
            for j in range(i + 1, len(titles))
        ]
        sample = rng.sample(pairs, min(len(pairs), 500))
        sims = sorted(_sim(a, b) for a, b in sample)
        if not sims:
            continue
        raw_p99 = sims[int(0.99 * len(sims))]
        cal_p99 = calibrate_sim(raw_p99, None, stats)
        cluster_p99[cluster] = cal_p99

    if not cluster_p99:
        return {"__global__": _BASELINE_THRESHOLD}

    global_p99 = sum(cluster_p99.values()) / len(cluster_p99)

    thresholds: dict[str, float] = {"__global__": _BASELINE_THRESHOLD}
    for cluster, p99 in cluster_p99.items():
        offset = (p99 - global_p99) * _CLUSTER_SENSITIVITY
        t = max(0.80, min(0.97, _BASELINE_THRESHOLD + offset))
        thresholds[cluster] = round(t, 4)

    return thresholds


def get_threshold_for_award(award_id: str | None, thresholds: dict | None = None) -> float:
    """賞IDからクラスタ経由でthresholdを返す。未知賞はglobalフォールバック。"""
    if thresholds is None:
        thresholds = get_cluster_thresholds()
    cluster = _CLUSTER_MAP.get(award_id or "", None)
    return thresholds.get(cluster, thresholds.get("__global__", _BASELINE_THRESHOLD))


# ─── Phase 19-C: 統合信頼度関数 ──────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_cluster_stability() -> dict[str, float]:
    """クラスタ別 stability = log(1+n_works) / log(1+n_ref) を返す。

    n_ref = 最大ワーク数クラスタ（literary ≈ 416）を基準。
    stability が低いクラスタ（horror: 0.45, sf: 0.68）は
    cluster_factor と bridge_bonus が抑制される。

    Returns:
        {cluster_id: stability_score}  ← "__global__" キーにフォールバック値あり
    """
    from collections import defaultdict

    cluster_works: dict[str, set[str]] = defaultdict(set)
    with open(PLAM_DIR / "award_history.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wid = row.get("work_id", "")
            aid = row.get("award_id", "")
            if wid and aid:
                cluster = _CLUSTER_MAP.get(aid, "unknown")
                cluster_works[cluster].add(wid)

    n_ref = max((len(v) for v in cluster_works.values()), default=1)
    stab: dict[str, float] = {}
    for cid, wids in cluster_works.items():
        n = len(wids)
        stab[cid] = round(math.log(1 + n) / math.log(1 + n_ref), 4)

    stab["__global__"] = round(sum(stab.values()) / len(stab), 4) if stab else 0.8
    return stab


@lru_cache(maxsize=1)
def get_bridge_work_ids() -> set[str]:
    """クラスタ横断作品（Bridge Work）の work_id セットを返す。

    award_history で2つ以上の異なるクラスタに属する作品を Bridge とする。
    """
    from collections import defaultdict

    work_clusters: dict[str, set[str]] = defaultdict(set)
    with open(PLAM_DIR / "award_history.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wid = row.get("work_id", "")
            aid = row.get("award_id", "")
            if wid and aid:
                cluster = _CLUSTER_MAP.get(aid, "unknown")
                work_clusters[wid].add(cluster)

    return {wid for wid, clusters in work_clusters.items() if len(clusters) >= 2}


def compute_final_score(
    base_calibrated: float,
    cluster_id: str | None,
    plam_work_id: str | None = None,
    stability: dict | None = None,
    bridge_ids: set | None = None,
) -> float:
    """Phase 19-C 統合信頼度スコア。

    設計:
        cluster_factor = BASE_WEIGHT + stability[cluster] × STABILITY_SCALE
        bridge_bonus   = BRIDGE_BONUS × stability[cluster]  (Bridge Workのみ)
        final = min(1.0, base_calibrated × cluster_factor + bridge_bonus)

    直感:
        - stability が高いクラスタ（literary≈1.0）→ cluster_factor≈1.0 →
          base_calibrated をほぼそのまま使う
        - stability が低いクラスタ（horror≈0.45）→ cluster_factor≈0.92 →
          境界付近のスコアが保守的に押し下げられる
        - Bridge Work → stability に応じた追加ボーナス
        - 比較用 threshold は単一グローバル値（0.85）で統一
    """
    if stability is None:
        stability = get_cluster_stability()
    if bridge_ids is None:
        bridge_ids = get_bridge_work_ids()

    stab = stability.get(cluster_id or "", stability.get("__global__", 0.8))
    cluster_factor = _CLUSTER_BASE_WEIGHT + stab * _CLUSTER_STABILITY_SCALE

    is_bridge = bool(plam_work_id and plam_work_id in bridge_ids)
    bonus = _BRIDGE_BONUS * stab if is_bridge else 0.0

    return min(1.0, base_calibrated * cluster_factor + bonus)


_UNIFIED_THRESHOLD = 0.85  # 19-C以降の単一グローバル閾値


def get_unified_threshold() -> float:
    """19-C以降で使う単一グローバル閾値を返す。"""
    return _UNIFIED_THRESHOLD


def calibration_report() -> str:
    """賞ごとの分布統計をテキスト形式で返す（デバッグ用）。"""
    stats = get_calibration_stats()
    lines = ["=== PLAM Calibration Stats ===", ""]
    lines.append(f"{'award':<12} {'mean':>8} {'std':>8} {'n':>6}")
    lines.append("-" * 38)
    for aid, s in sorted(stats.items()):
        if aid == "__global__":
            continue
        lines.append(f"{aid:<12} {s['mean']:>8.5f} {s['std']:>8.5f} {s['n']:>6}")
    g = stats.get("__global__", {})
    lines.append("-" * 38)
    lines.append(f"{'[global]':<12} {g.get('mean',0):>8.5f} {g.get('std',0):>8.5f}")
    return "\n".join(lines)

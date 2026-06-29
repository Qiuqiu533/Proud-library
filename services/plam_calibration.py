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

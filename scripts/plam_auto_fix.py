"""
plam_auto_fix.py — award_books.plam_work_id を信頼スコアに基づいて自動補完する。

使い方:
    python scripts/plam_auto_fix.py --dry-run               # 候補表示（DB変更なし）
    python scripts/plam_auto_fix.py --apply                 # 全候補を確定（デフォルトthreshold=0.85）
    python scripts/plam_auto_fix.py --auto-fix              # threshold以上を自動確定（ログ記録）
    python scripts/plam_auto_fix.py --auto-fix --threshold 0.92

信頼スコア（0.0〜1.0）の計算式:
    title_sim   : タイトル正規化後の文字列類似度（SequenceMatcher）
    author_ok   : 著者一致ボーナス（+0.10）
    award_bonus : award_books.award がPLAM award_history に同名賞あり（+0.05）
    score = title_sim * 0.85 + author_ok + award_bonus
    → score >= threshold のみ自動確定

閾値ガイド:
    0.95+ : 完全一致クラス（ほぼ誤りなし）
    0.90  : 揺れ許容（推奨デフォルト）
    0.85  : 積極モード（低リスクな揺れを捕捉）
    0.80以下: 要人間レビュー
"""
import argparse
import csv
import sys
import unicodedata
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PLAM_DIR = ROOT / "data" / "plam"
DEFAULT_THRESHOLD = 0.90


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower()
    s = re.sub(r"[\s　]+", "", s)
    return s


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _load_plam_works() -> dict[str, dict]:
    result: dict[str, dict] = {}
    with open(PLAM_DIR / "works.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("canonical_title", "")
            if t:
                result[_normalize(t)] = row
    return result


def _load_award_history_titles() -> set[str]:
    """award_history.csv の award_id セット（賞名ボーナス判定用）"""
    awards: set[str] = set()
    path = PLAM_DIR / "award_history.csv"
    if not path.exists():
        return awards
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = row.get("award_id", "") or row.get("award", "")
            if a:
                awards.add(_normalize(a))
    return awards


def _score_candidate(
    db_title: str,
    db_author: str,
    db_award: str,
    plam_work: dict,
    plam_award_ids: set[str],
    cal_stats: dict,
) -> tuple[float, str]:
    """キャリブレーション済み信頼スコアと fix_type を返す"""
    from services.plam_calibration import calibrated_score

    pt = _normalize(plam_work.get("canonical_title", ""))
    dt = _normalize(db_title)
    pa = _normalize(plam_work.get("author", ""))
    da = _normalize(db_author or "")
    raw_sim = _sim(dt, pt)

    has_award = _normalize(db_award) in plam_award_ids
    score = calibrated_score(
        db_title, db_author, db_award,
        plam_work.get("canonical_title", ""),
        plam_work.get("author", ""),
        stats=cal_stats,
        has_award_match=has_award,
    )

    # fix_type は raw_sim で判定（キャリブレーション後スコアは閾値判定に使う）
    if raw_sim >= 0.99 and (not da or not pa or da == pa or da in pa or pa in da):
        fix_type = "exact"
    elif raw_sim >= 0.85:
        fix_type = "title_variant"
    elif raw_sim >= 0.60:
        fix_type = "partial_match"
    else:
        fix_type = "weak_match"

    return score, fix_type


def _find_candidates(
    title: str,
    author: str,
    award: str,
    plam_idx: dict[str, dict],
    plam_award_ids: set[str],
    cal_stats: dict,
    min_sim: float = 0.55,
) -> list[tuple[float, str, dict]]:
    """(calibrated_score, fix_type, plam_work) のリスト（スコア降順）"""
    dt = _normalize(title)
    results = []
    for pt, work in plam_idx.items():
        ts = _sim(dt, pt)
        if ts < min_sim:
            continue
        score, fix_type = _score_candidate(title, author, award, work, plam_award_ids, cal_stats)
        results.append((score, fix_type, work))
    results.sort(key=lambda x: -x[0])
    return results[:5]


def build_fix_list(con, plam_idx, plam_award_ids, cal_stats, threshold: float) -> list[dict]:
    """閾値以上のすべての自動修正候補を返す"""
    cur = con.cursor()
    cur.execute("""
        SELECT id, award, award_year, title, author
        FROM award_books
        WHERE status='確認済' AND plam_work_id IS NULL
        ORDER BY award, award_year DESC NULLS LAST
    """)
    rows = cur.fetchall()

    fixes = []
    for rid, award, year, title, author in rows:
        candidates = _find_candidates(
            title, author or "", award, plam_idx, plam_award_ids, cal_stats
        )
        if not candidates:
            continue
        top_score, fix_type, top_work = candidates[0]
        if top_score >= threshold:
            fixes.append({
                "id": rid,
                "award": award,
                "year": year,
                "db_title": title,
                "db_author": author or "",
                "plam_work_id": top_work["work_id"],
                "plam_title": top_work.get("canonical_title", ""),
                "plam_author": top_work.get("author", ""),
                "confidence": round(top_score, 4),
                "fix_type": fix_type,
            })
    return fixes


def cmd_dry_run(con, plam_idx, plam_award_ids, cal_stats, threshold: float):
    fixes = build_fix_list(con, plam_idx, plam_award_ids, cal_stats, threshold)

    print(f"\n=== auto-fix 候補 (threshold={threshold}) ===")
    print(f"対象: {len(fixes)}件\n")

    by_type: dict[str, list] = {}
    for f in fixes:
        by_type.setdefault(f["fix_type"], []).append(f)

    for ftype, items in sorted(by_type.items()):
        print(f"--- {ftype} ({len(items)}件) ---")
        for f in items:
            print(f"  [{f['confidence']:.3f}] {f['award']} {f['year'] or '?'}年")
            print(f"    DB   : 「{f['db_title']}」著: {f['db_author'] or '?'}")
            print(f"    PLAM : 「{f['plam_title']}」著: {f['plam_author']}  ({f['plam_work_id']})")


def _do_apply(con, fixes: list[dict], mode: str):
    cur = con.cursor()
    applied = 0
    for f in fixes:
        cur.execute(
            "UPDATE award_books SET plam_work_id=%s WHERE id=%s AND plam_work_id IS NULL",
            (f["plam_work_id"], f["id"])
        )
        # fix_log 記録
        try:
            cur.execute("""
                INSERT INTO plam_fix_log
                (award_book_id, award, award_year, db_title, db_author,
                 plam_work_id, plam_title, plam_author, confidence, fix_type, mode)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                f["id"], f["award"], f["year"], f["db_title"], f["db_author"],
                f["plam_work_id"], f["plam_title"], f["plam_author"],
                f["confidence"], f["fix_type"], mode
            ))
        except Exception as e:
            print(f"[warn] fix_log 記録スキップ: {e}")
        applied += 1

    con.commit()

    # coverage_log 更新
    cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済'")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済' AND plam_work_id IS NOT NULL")
    linked = cur.fetchone()[0]
    pct = round(linked / total * 100, 1) if total else 0
    try:
        cur.execute(
            "INSERT INTO plam_coverage_log (total, linked, coverage_pct, note) VALUES (%s,%s,%s,%s)",
            (total, linked, pct, f"{mode} +{applied}件")
        )
        con.commit()
    except Exception as e:
        print(f"[warn] coverage_log 記録スキップ: {e}")

    print(f"\n適用完了: {applied}件  カバレッジ: {pct}% ({linked}/{total})")


def cmd_apply(con, plam_idx, plam_award_ids, cal_stats, threshold: float):
    fixes = build_fix_list(con, plam_idx, plam_award_ids, cal_stats, threshold)
    if not fixes:
        print(f"threshold={threshold} 以上の候補はありませんでした。")
        return
    print(f"適用対象: {len(fixes)}件 (threshold={threshold})")
    _do_apply(con, fixes, mode="apply")


def cmd_auto_fix(con, plam_idx, plam_award_ids, cal_stats, threshold: float):
    if threshold < 0.85:
        print(f"[abort] threshold={threshold} は危険域です（0.85未満は手動レビュー推奨）。")
        sys.exit(1)
    fixes = build_fix_list(con, plam_idx, plam_award_ids, cal_stats, threshold)
    if not fixes:
        print(f"threshold={threshold} 以上の候補はありませんでした。")
        return
    print(f"自動修正対象: {len(fixes)}件 (threshold={threshold})")
    _do_apply(con, fixes, mode=f"auto-fix@{threshold}")


def main():
    parser = argparse.ArgumentParser(description="PLAMオートフィックス")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run",   action="store_true", help="候補表示のみ")
    group.add_argument("--apply",     action="store_true", help="全候補を確定")
    group.add_argument("--auto-fix",  action="store_true", help="threshold以上を自動確定")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"信頼スコア閾値（デフォルト: {DEFAULT_THRESHOLD}）")
    args = parser.parse_args()

    from database import get_con, USE_PG
    if not USE_PG:
        print("このスクリプトはPostgreSQL環境（本番）でのみ動作します。")
        sys.exit(1)

    plam_idx = _load_plam_works()
    plam_award_ids = _load_award_history_titles()
    print(f"PLAMインデックス: {len(plam_idx)}作品  賞IDセット: {len(plam_award_ids)}件")

    from services.plam_calibration import get_calibration_stats, calibration_report
    cal_stats = get_calibration_stats()
    print(f"キャリブレーション統計: {len(cal_stats)-1}賞")
    print(calibration_report())

    con = get_con()
    try:
        if args.dry_run:
            cmd_dry_run(con, plam_idx, plam_award_ids, cal_stats, args.threshold)
        elif args.apply:
            cmd_apply(con, plam_idx, plam_award_ids, cal_stats, args.threshold)
        elif args.auto_fix:
            cmd_auto_fix(con, plam_idx, plam_award_ids, cal_stats, args.threshold)
    finally:
        con.close()


if __name__ == "__main__":
    main()

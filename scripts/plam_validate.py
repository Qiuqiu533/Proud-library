"""
PLAM CSV 品質検証スクリプト

使い方:
  python3 scripts/plam_validate.py data/plam/akutagawa_prize.csv [phase1_start] [phase1_end]
  python3 scripts/plam_validate.py data/plam/naoki_prize.csv 1 72
"""
from __future__ import annotations
import csv, sys, os
from pathlib import Path
from datetime import datetime
from collections import defaultdict


VALID_STATUSES = {"awarded", "no_award", "co_winner"}
VALID_TERMS    = {"H1", "H2"}


def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            if line.startswith("work_id") or line.startswith("award_id"):
                break
        f.seek(0)
        reader = csv.DictReader(filter(lambda l: not l.startswith("#"), f))
        rows = list(reader)
    return rows


def validate(path: str, no_start: int | None = None, no_end: int | None = None) -> tuple[bool, list[str]]:
    rows = load_csv(path)
    errors: list[str] = []
    award_name = rows[0]["award_name"] if rows else path

    # ── 1. award_term ──────────────────────────────
    for r in rows:
        if r["award_term"] not in VALID_TERMS:
            errors.append(f"[award_term] 不正値: 回{r['award_no']} '{r['award_term']}'")

    # ── 2. status ──────────────────────────────────
    for r in rows:
        if r["status"] not in VALID_STATUSES:
            errors.append(f"[status] 不正値: 回{r['award_no']} '{r['status']}'")

    # ── 3. no_award は1回1件のみ ───────────────────
    no_award_by_round: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["status"] == "no_award":
            key = (r["award_no"], r["award_term"])
            no_award_by_round[key].append(r)
    for key, recs in no_award_by_round.items():
        if len(recs) > 1:
            errors.append(f"[no_award重複] 第{key[0]}回{key[1]}: {len(recs)}件（1件のみ許可）")

    # ── 4. awarded と no_award は同一回に共存不可 ──
    by_round: dict[tuple, list] = defaultdict(list)
    for r in rows:
        by_round[(r["award_no"], r["award_term"])].append(r["status"])
    for key, statuses in by_round.items():
        if "no_award" in statuses and len(statuses) > 1:
            errors.append(f"[矛盾] 第{key[0]}回{key[1]}: no_award と受賞作が混在")

    # ── 5. 回次整合性（欠番チェック）─────────────
    if no_start and no_end:
        existing_nos = {int(r["award_no"]) for r in rows}
        expected = set(range(no_start, no_end + 1))
        missing = expected - existing_nos
        extra   = existing_nos - expected
        if missing:
            errors.append(f"[回次欠番] {sorted(missing)}")
        if extra:
            errors.append(f"[想定外の回次] {sorted(extra)}")

    # ── 6. 件数整合性 ────────────────────────────
    total      = len(rows)
    n_awarded  = sum(1 for r in rows if r["status"] in ("awarded", "co_winner"))
    n_no_award = sum(1 for r in rows if r["status"] == "no_award")
    if total != n_awarded + n_no_award:
        errors.append(f"[件数不整合] 総計{total} ≠ 受賞{n_awarded} + 該当なし{n_no_award}")

    # ── 7. work_id 重複 ──────────────────────────
    if "work_id" in (rows[0] if rows else {}):
        seen_ids: set[str] = set()
        for r in rows:
            wid = r.get("work_id", "")
            if wid in seen_ids:
                errors.append(f"[work_id重複] {wid}")
            seen_ids.add(wid)

    # ── サマリー出力 ────────────────────────────
    n_co_rounds = len({(r["award_no"], r["award_term"]) for r in rows if r["status"] == "co_winner"})
    print(f"\n{'='*50}")
    print(f"  {award_name} ({Path(path).name})")
    print(f"{'='*50}")
    print(f"  総レコード数   : {total}")
    print(f"  受賞作品数     : {n_awarded}")
    print(f"  該当作なし件数 : {n_no_award}")
    print(f"  共同受賞回数   : {n_co_rounds}")
    print(f"  検証結果       : {'✅ OK' if not errors else f'❌ {len(errors)}件のエラー'}")
    for e in errors:
        print(f"    → {e}")

    return (len(errors) == 0), errors


def write_error_log(errors_by_file: dict[str, list[str]]) -> None:
    path = "data/plam/validation_errors.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# PLAM 検証エラーログ\n\n生成日時: {datetime.now():%Y-%m-%d %H:%M}\n\n")
        for filename, errors in errors_by_file.items():
            f.write(f"## {filename}\n\n")
            for e in errors:
                f.write(f"- {e}\n")
            f.write("\n")
    print(f"\n  ⚠️  エラーログを書き出しました: {path}")


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else []

    # 引数なしの場合は data/plam/*.csv を全件チェック
    if not targets:
        targets = sorted(str(p) for p in Path("data/plam").glob("*.csv")
                         if p.name != "awards_master.csv")

    all_ok = True
    errors_by_file: dict[str, list[str]] = {}

    for t in targets:
        ok, errs = validate(t)
        if not ok:
            all_ok = False
            errors_by_file[t] = errs

    if errors_by_file:
        write_error_log(errors_by_file)
        sys.exit(1)
    else:
        print("\n✅ 全チェック通過 — コミット可能\n")
        # validation_errors.md があれば削除
        err_path = Path("data/plam/validation_errors.md")
        if err_path.exists():
            err_path.unlink()

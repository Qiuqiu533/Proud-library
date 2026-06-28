"""
PLAM Version 1.4 — 横断検証スクリプト

award_history.csv × works.csv の整合性を検証する。

検証項目:
1. work_id欠損（受賞行なのにwork_idが空）
2. award_id欠損
3. history重複（同一work_id × award_id × award_no × award_term）
4. 同一賞・同一回の award_no+award_term 重複（上限なし、共同受賞は許可）
5. works.csv との整合性（award_historyのwork_idがworks.csvに存在するか）
6. 孤立work_id（works.csvにあるがaward_historyに出てこない作品）

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/cross_award_validate.py
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
from collections import defaultdict

PLAM_DIR     = Path("data/plam")
HISTORY_PATH = PLAM_DIR / "award_history.csv"
WORKS_PATH   = PLAM_DIR / "works.csv"


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


def main() -> bool:
    errors: list[str] = []

    if not HISTORY_PATH.exists():
        print("❌ award_history.csv が存在しません。先に plam_build_award_history.py を実行してください。")
        return False

    history = read_csv(HISTORY_PATH)
    works   = read_csv(WORKS_PATH)

    works_ids = {r["work_id"] for r in works if r.get("work_id")}
    history_work_ids: set[str] = set()

    # ── 1. work_id欠損 ───────────────────────────────────────────
    for r in history:
        if not r.get("work_id", "").strip():
            errors.append(f"[work_id欠損] history_id={r.get('history_id')} award_id={r.get('award_id')}")

    # ── 2. award_id欠損 ──────────────────────────────────────────
    for r in history:
        if not r.get("award_id", "").strip():
            errors.append(f"[award_id欠損] history_id={r.get('history_id')} work_id={r.get('work_id')}")

    # ── 3. history重複（完全一致行）──────────────────────────────
    seen_keys: set[tuple] = set()
    for r in history:
        key = (r.get("work_id"), r.get("award_id"), r.get("award_no"), r.get("award_term"))
        if key in seen_keys:
            errors.append(f"[history重複] {key}")
        seen_keys.add(key)

    # ── 4. 同一賞・同一回重複 ────────────────────────────────────
    # 注: 共同受賞は同一回に複数 work_id が存在して OK
    # 同一 work_id が同一賞・同一回に2回以上あればエラー
    round_works: dict[tuple, list[str]] = defaultdict(list)
    for r in history:
        key = (r.get("award_id"), r.get("award_no"), r.get("award_term"), r.get("work_id"))
        round_works[key[:3]].append(r.get("work_id", ""))

    # 同一 work_id が同一ラウンドに重複（つまりkeyが重複、上記[3]で既にチェック済み）
    # ここでは同じ round に 10件以上あるなど異常を検出
    for (aid, ano, aterm), wids in round_works.items():
        if len(wids) > 5:
            errors.append(f"[異常多数] {aid} 第{ano}回{aterm}: {len(wids)}件")

    # ── 5. works.csv との整合性 ──────────────────────────────────
    for r in history:
        wid = r.get("work_id", "").strip()
        if wid:
            history_work_ids.add(wid)
            if wid not in works_ids:
                errors.append(f"[works不整合] work_id={wid} が works.csv に存在しない")

    # ── 6. 孤立work_id ───────────────────────────────────────────
    orphan = works_ids - history_work_ids
    if orphan:
        # no_award 行は history に入らないので孤立は正常でない
        # ただし現状は import前なので警告にとどめる
        print(f"  ℹ️  award_historyに未登録のwork_id: {len(orphan)} 件（works.csvにはある）")

    # ── サマリー ─────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"  cross_award_validate.py")
    print(f"{'='*50}")
    print(f"  award_history: {len(history)} 行")
    print(f"  works.csv:     {len(works)} 作品")
    print(f"  複数受賞work:  {sum(1 for wid, cnt in _count_awards(history).items() if cnt > 1)} 件")
    print(f"  検証結果:      {'✅ OK' if not errors else f'❌ {len(errors)}件のエラー'}")
    for e in errors[:20]:
        print(f"    → {e}")
    if len(errors) > 20:
        print(f"    ... 他 {len(errors)-20} 件")

    return len(errors) == 0


def _count_awards(history: list[dict]) -> dict[str, int]:
    from collections import Counter
    return Counter(r["work_id"] for r in history if r.get("work_id"))


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)

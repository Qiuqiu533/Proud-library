"""
award_books（受賞作DB）シードデータの品質チェックツール。

seeds.py の _AWARD_BOOKS_SEED を対象に以下を検証する:
  - 重複レコード（award, award_no, award_year, title, author）
  - タイトル・著者名の空欄
  - award_name の表記ゆれ（既知の正規名一覧との照合）
  - award_category の表記ゆれ（賞ごとの正規部門一覧との照合）
  - 年×部門ごとの件数集計（異常値の目視確認用）

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/check_awards.py
  → 全チェックがOKなら exit 0、問題があれば内容を表示して exit 1
"""
from __future__ import annotations
import sys
import os
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from seeds import _AWARD_BOOKS_SEED  # noqa: E402

# ── 正規化済み賞名一覧（表記ゆれ検出用） ────────────────────────────────
KNOWN_AWARD_NAMES = {
    "芥川賞", "直木賞", "本屋大賞", "山本周五郎賞", "谷崎潤一郎賞",
    "三島由紀夫賞", "野間文芸賞", "読売文学賞", "川端康成文学賞",
    "柴田錬三郎賞", "吉川英治文学賞", "江戸川乱歩賞",
}

# ── 部門制の賞の正規部門一覧（2026-07-04確定） ──────────────────────────
AWARD_CATEGORIES = {
    "読売文学賞": {"小説賞", "戯曲・シナリオ賞", "随筆・紀行賞", "評論・伝記賞", "詩歌俳句賞", "研究・翻訳賞"},
}

# 部門なしの賞（award_categoryは必ず空文字であるべき）
NO_CATEGORY_AWARDS = {"芥川賞", "直木賞", "本屋大賞", "山本周五郎賞", "谷崎潤一郎賞", "三島由紀夫賞", "野間文芸賞"}


def _normalize(t):
    """6要素タプルなら7要素目に空文字を補って正規化する。"""
    return t if len(t) == 7 else (t + ("",))


def check_duplicates(rows):
    entries = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
    seen = set()
    dups = []
    for e in entries:
        if e in seen:
            dups.append(e)
        seen.add(e)
    return dups


def check_empty_fields(rows):
    problems = []
    for r in rows:
        award, no, year, title, author = r[0], r[1], r[2], r[3], r[4]
        if not title or not title.strip():
            problems.append(("タイトル空欄", (award, no, year, title, author)))
        if author is None or not str(author).strip():
            problems.append(("著者空欄", (award, no, year, title, author)))
    return problems


def check_award_name_spelling(rows):
    unknown = sorted({r[0] for r in rows if r[0] not in KNOWN_AWARD_NAMES})
    return unknown


def check_award_category_spelling(rows):
    problems = []
    for r in rows:
        award, category = r[0], r[6]
        if award in NO_CATEGORY_AWARDS:
            if category:
                problems.append((award, r[1], r[2], r[3], f"部門なしのはずだがaward_category='{category}'"))
        elif award in AWARD_CATEGORIES:
            if category and category not in AWARD_CATEGORIES[award]:
                problems.append((award, r[1], r[2], r[3], f"未知の部門名'{category}'"))
    return problems


def year_category_summary(rows):
    """(award, year, category) ごとの件数を集計する。"""
    counter = Counter((r[0], r[2], r[6]) for r in rows)
    return dict(sorted(counter.items()))


def main() -> int:
    rows = [_normalize(t) for t in _AWARD_BOOKS_SEED]
    ok = True

    print(f"総レコード数: {len(rows)}件\n")

    dups = check_duplicates(rows)
    if dups:
        ok = False
        print(f"❌ 重複レコード: {len(dups)}件")
        for d in dups:
            print(f"   {d}")
    else:
        print("✓ 重複なし")

    empties = check_empty_fields(rows)
    if empties:
        ok = False
        print(f"❌ 空欄フィールド: {len(empties)}件")
        for kind, e in empties:
            print(f"   [{kind}] {e}")
    else:
        print("✓ タイトル・著者の空欄なし")

    unknown_awards = check_award_name_spelling(rows)
    if unknown_awards:
        print(f"⚠️  未登録の賞名（KNOWN_AWARD_NAMESに追加要検討）: {unknown_awards}")
    else:
        print("✓ award_name表記ゆれなし")

    category_problems = check_award_category_spelling(rows)
    if category_problems:
        ok = False
        print(f"❌ award_category不整合: {len(category_problems)}件")
        for p in category_problems:
            print(f"   {p}")
    else:
        print("✓ award_category表記OK")

    print("\n--- 年×部門 件数集計（異常値の目視確認用） ---")
    for (award, year, category), count in year_category_summary(rows).items():
        label = f"{award} {year} {category or '(部門なし)'}"
        flag = " ⚠️ 3件以上" if count >= 3 else ""
        print(f"  {label}: {count}件{flag}")

    print()
    if ok:
        print("✅ CSV形式チェック: 全項目OK")
        return 0
    else:
        print("❌ 問題が見つかりました。上記を確認してください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""
PLAM Version 1.5 — 重複判定パイプライン

【work_id 永久不変ルール】
  既存 work_id は絶対に再採番しない。
  新規作品にのみ新しい work_id を採番する。
  重複判定で既存作品と一致した場合は既存 work_id を再利用する。

【4段階マッチング優先順位】
  1. ISBN一致          → 同一作品として自動確定
  2. canonical_title + author_id 一致 → 同一作品として自動採用
  3. canonical_title 一致のみ → duplicate_candidates.csv に出力してレビュー対象
  4. いずれも不一致   → 新しい work_id を採番

使い方:
  # 1. works.csv を V1.5 形式にアップグレード（初回のみ）
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_build_v15.py --upgrade

  # 2. 新しい賞 CSV を取り込む
  python3 scripts/plam_build_v15.py --import data/plam/honnya_prize.csv

  # 3. ドライラン（書き込みなし）
  python3 scripts/plam_build_v15.py --import data/plam/honnya_prize.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PLAM_DIR       = Path("data/plam")
WORKS_PATH     = PLAM_DIR / "works.csv"
AUTHORS_PATH   = PLAM_DIR / "authors.csv"
DUP_PATH       = PLAM_DIR / "duplicate_candidates.csv"
REPORTS_DIR    = Path("reports")
MATCH_REPORT   = REPORTS_DIR / "work_matching_report.md"

WORKS_FIELDS   = ["work_id", "canonical_title", "title", "author",
                  "author_id", "isbn13", "isbn_status", "notes"]
AUTHORS_FIELDS = ["author_id", "author_name", "author_name_kana",
                  "birth_year", "death_year", "notes"]
DUP_FIELDS     = ["candidate_work_id", "incoming_title", "matched_title",
                  "incoming_author", "matched_author",
                  "match_reason", "confidence", "source_csv"]

EXCLUDE = {"awards_master.csv", "works.csv", "authors.csv",
           "aliases.csv", "award_history.csv",
           "duplicate_candidates.csv"}


# ── ユーティリティ ──────────────────────────────────────────────────────────

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    if not lines:
        return []
    return list(csv.DictReader(lines))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def normalize_title(s: str) -> str:
    """canonical_title 比較用: 記号・空白を除去して小文字化"""
    return re.sub(r"[\s　・〜～／/「」『』（）()【】\-―—]", "", (s or "")).lower()


def normalize_author(s: str) -> str:
    return re.sub(r"[\s　]", "", (s or "")).lower()


def next_id(prefix: str, existing: set[str]) -> str:
    """PLAM-XXXXXX または AUTR-XXXXXX を採番"""
    nums = set()
    for eid in existing:
        if eid.startswith(prefix):
            try:
                nums.add(int(eid[len(prefix):]))
            except ValueError:
                pass
    n = max(nums, default=0) + 1
    while f"{prefix}{n:06d}" in existing:
        n += 1
    return f"{prefix}{n:06d}"


# ── works / authors レジストリ ────────────────────────────────────────────────

class WorkRegistry:
    """既存 works.csv を保持し、不変性を保ちながらマッチングと追加を行う"""

    def __init__(self):
        self.rows: list[dict] = []
        self._by_isbn:  dict[str, dict] = {}   # isbn13 → row
        self._by_key:   dict[str, dict] = {}   # canonical_title||author_id → row
        self._by_title: dict[str, list[dict]] = defaultdict(list)  # canonical_title → rows
        self._ids: set[str] = set()

    def load(self) -> None:
        self.rows = read_csv(WORKS_PATH)
        for r in self.rows:
            wid = r.get("work_id", "")
            self._ids.add(wid)
            isbn = (r.get("isbn13") or "").strip()
            if isbn:
                self._by_isbn[isbn] = r
            ct = normalize_title(r.get("canonical_title") or r.get("title", ""))
            aid = (r.get("author_id") or "").strip()
            if ct and aid:
                self._by_key[f"{ct}||{aid}"] = r
            if ct:
                self._by_title[ct].append(r)

    def match(self, title: str, author: str, isbn: str, author_id: str
              ) -> tuple[str, dict | None, str, str]:
        """
        戻り値: (tier, matched_row, match_reason, confidence)
        tier: "ISBN" | "KEY" | "TITLE" | "NEW"
        """
        isbn = (isbn or "").strip()
        ct   = normalize_title(title)
        aid  = (author_id or "").strip()

        # Tier 1: ISBN一致
        if isbn and isbn in self._by_isbn:
            r = self._by_isbn[isbn]
            return "ISBN", r, f"ISBN一致: {isbn}", "HIGH"

        # Tier 2: canonical_title + author_id 一致
        key = f"{ct}||{aid}"
        if ct and aid and key in self._by_key:
            r = self._by_key[key]
            return "KEY", r, "canonical_title+author_id一致", "HIGH"

        # Tier 3: canonical_title のみ一致
        if ct and ct in self._by_title:
            candidates = self._by_title[ct]
            conf = "HIGH" if len(candidates) == 1 else "MEDIUM"
            return "TITLE", candidates[0], f"canonical_titleのみ一致(候補{len(candidates)}件)", conf

        return "NEW", None, "新規作品", "—"

    def add(self, row: dict) -> None:
        """新規作品を追加（IDは呼び出し側で設定済み）"""
        self.rows.append(row)
        self._ids.add(row["work_id"])
        isbn = (row.get("isbn13") or "").strip()
        if isbn:
            self._by_isbn[isbn] = row
        ct = normalize_title(row.get("canonical_title") or row.get("title", ""))
        aid = (row.get("author_id") or "").strip()
        if ct and aid:
            self._by_key[f"{ct}||{aid}"] = row
        if ct:
            self._by_title[ct].append(row)

    def next_work_id(self) -> str:
        return next_id("PLAM-", self._ids)

    def save(self) -> None:
        write_csv(WORKS_PATH, WORKS_FIELDS, self.rows)


class AuthorRegistry:
    """既存 authors.csv を保持し、author_id を解決する"""

    def __init__(self):
        self.rows: list[dict] = []
        self._by_name: dict[str, dict] = {}   # normalize_author(name) → row
        self._ids: set[str] = set()

    def load(self) -> None:
        self.rows = read_csv(AUTHORS_PATH)
        for r in self.rows:
            self._ids.add(r.get("author_id", ""))
            key = normalize_author(r.get("author_name", ""))
            if key:
                self._by_name[key] = r

    def resolve(self, author_name: str) -> str:
        """著者名 → author_id（なければ新規採番・追加）"""
        key = normalize_author(author_name)
        if not key:
            return ""
        if key in self._by_name:
            return self._by_name[key]["author_id"]
        # 新規追加
        aid = next_id("AUTR-", self._ids)
        row = {"author_id": aid, "author_name": author_name,
               "author_name_kana": "", "birth_year": "", "death_year": "", "notes": ""}
        self.rows.append(row)
        self._ids.add(aid)
        self._by_name[key] = row
        return aid

    def save(self) -> None:
        write_csv(AUTHORS_PATH, AUTHORS_FIELDS, self.rows)


# ── --upgrade: works.csv を V1.5 形式に一回限りの移行 ─────────────────────

def cmd_upgrade(dry_run: bool) -> None:
    """
    works.csv に canonical_title / author_id 列を追加する（既存行の移行）。
    authors.csv を参照して author_id を解決する。
    """
    print("=== PLAM V1.5 アップグレード ===")
    works_rows = read_csv(WORKS_PATH)
    if not works_rows:
        print("❌ works.csv が空またはありません")
        sys.exit(1)

    # 既に V1.5 形式かチェック
    if "canonical_title" in works_rows[0] and "author_id" in works_rows[0]:
        print("✅ works.csv は既に V1.5 形式です（canonical_title/author_id あり）")
        return

    authors = AuthorRegistry()
    authors.load()

    upgraded = 0
    for r in works_rows:
        # canonical_title: 既存の title をそのまま
        r.setdefault("canonical_title", r.get("title", ""))
        # author_id: authors.csv を参照して解決
        existing_aid = r.get("author_id", "").strip()
        if not existing_aid:
            r["author_id"] = authors.resolve(r.get("author", ""))
        upgraded += 1

    print(f"  works.csv: {upgraded} 行に canonical_title / author_id を付与")
    print(f"  authors.csv: {len(authors.rows)} 名（新規追加含む）")

    if not dry_run:
        write_csv(WORKS_PATH, WORKS_FIELDS, works_rows)
        authors.save()
        print("✅ アップグレード完了")
    else:
        print("[dry-run] 書き込みなし")


# ── --import: 新しい賞 CSV を 4段階マッチングで取り込む ────────────────────

def cmd_import(csv_path: Path, dry_run: bool) -> None:
    if not csv_path.exists():
        print(f"❌ ファイルが見つかりません: {csv_path}")
        sys.exit(1)

    # works.csv が V1.5 形式かチェック
    sample = read_csv(WORKS_PATH)
    if sample and ("canonical_title" not in sample[0] or "author_id" not in sample[0]):
        print("❌ works.csv が V1.5 形式ではありません。先に --upgrade を実行してください。")
        sys.exit(1)

    print(f"=== PLAM V1.5 インポート: {csv_path.name} ===")
    REPORTS_DIR.mkdir(exist_ok=True)

    works   = WorkRegistry()
    authors = AuthorRegistry()
    works.load()
    authors.load()

    incoming = read_csv(csv_path)
    if not incoming:
        print("❌ 対象CSVが空です")
        sys.exit(1)

    # カウンタ
    cnt = {"total": 0, "no_award": 0,
           "isbn": 0, "key": 0, "title": 0, "new": 0, "skip": 0}

    new_award_rows: list[dict] = []  # 更新後の award CSV 行
    dup_rows: list[dict] = []        # duplicate_candidates

    for r in incoming:
        cnt["total"] += 1

        if r.get("status") == "no_award":
            cnt["no_award"] += 1
            new_award_rows.append(r)
            continue

        title  = (r.get("title") or "").strip()
        author = (r.get("author") or "").strip()
        isbn   = (r.get("isbn13") or "").strip()

        if not title or not author:
            cnt["skip"] += 1
            new_award_rows.append(r)
            continue

        # author_id 解決
        aid = authors.resolve(author)

        # 4段階マッチング
        tier, matched, reason, conf = works.match(title, author, isbn, aid)

        nr = dict(r)

        if tier in ("ISBN", "KEY"):
            # Tier 1/2: 既存 work_id 再利用
            nr["work_id"] = matched["work_id"]
            cnt[tier.lower()] += 1

        elif tier == "TITLE":
            # Tier 3: レビュー対象 → duplicate_candidates に出力
            # award CSV は work_id 空のまま残す（人が確認後に手動修正）
            nr["work_id"] = ""
            dup_rows.append({
                "candidate_work_id": matched["work_id"],
                "incoming_title":    title,
                "matched_title":     matched.get("canonical_title") or matched.get("title", ""),
                "incoming_author":   author,
                "matched_author":    matched.get("author", ""),
                "match_reason":      reason,
                "confidence":        conf,
                "source_csv":        csv_path.name,
            })
            cnt["title"] += 1

        else:
            # Tier 4: 新規作品
            wid = works.next_work_id()
            nr["work_id"] = wid
            works.add({
                "work_id":        wid,
                "canonical_title": title,
                "title":          title,
                "author":         author,
                "author_id":      aid,
                "isbn13":         isbn,
                "isbn_status":    r.get("isbn_status", "missing"),
                "notes":          "",
            })
            cnt["new"] += 1

        new_award_rows.append(nr)

    # ── 出力 ─────────────────────────────────────────────────────────────────
    awarded_total = cnt["total"] - cnt["no_award"] - cnt["skip"]
    auto_matched  = cnt["isbn"] + cnt["key"]

    print(f"\n  処理対象: {awarded_total} 件（うちno_award {cnt['no_award']} 件）")
    print(f"  Tier 1 ISBN一致:               {cnt['isbn']:3d} 件")
    print(f"  Tier 2 canonical+author_id一致: {cnt['key']:3d} 件")
    print(f"  Tier 3 titleのみ一致（要確認）:  {cnt['title']:3d} 件")
    print(f"  Tier 4 新規 work_id 採番:       {cnt['new']:3d} 件")

    if not dry_run:
        # award CSV を更新（work_id を書き込む）
        fieldnames = list(incoming[0].keys())
        write_csv(csv_path, fieldnames, new_award_rows)
        print(f"  ✅ {csv_path.name} 更新（work_id付与）")

        # works.csv / authors.csv を保存
        works.save()
        authors.save()
        print(f"  ✅ works.csv: {len(works.rows)} 作品")
        print(f"  ✅ authors.csv: {len(authors.rows)} 名")

        # duplicate_candidates.csv
        if dup_rows:
            existing_dups = read_csv(DUP_PATH)
            write_csv(DUP_PATH, DUP_FIELDS, existing_dups + dup_rows)
            print(f"  ⚠️  duplicate_candidates.csv: {len(dup_rows)} 件追加（要確認）")
        else:
            print(f"  ✅ duplicate_candidates: 0 件（全自動解決）")

        # work_matching_report.md
        _write_report(csv_path, cnt, awarded_total, auto_matched, dup_rows)
        print(f"  ✅ {MATCH_REPORT}")
    else:
        print("[dry-run] 書き込みなし")
        if dup_rows:
            print(f"\n  要確認候補:")
            for d in dup_rows:
                print(f"    {d['incoming_title']} / {d['incoming_author']}"
                      f" → {d['candidate_work_id']} ({d['match_reason']}, {d['confidence']})")


def _write_report(csv_path: Path, cnt: dict, awarded_total: int,
                  auto_matched: int, dup_rows: list[dict]) -> None:
    lines = [
        f"# PLAM work_matching_report.md",
        f"",
        f"生成日時: {datetime.now():%Y-%m-%d %H:%M}",
        f"インポート対象: `{csv_path.name}`",
        f"",
        f"## サマリー",
        f"",
        f"| 項目 | 件数 |",
        f"|---|---|",
        f"| 処理対象（受賞行） | {awarded_total} |",
        f"| Tier 1 ISBN一致（自動確定） | {cnt['isbn']} |",
        f"| Tier 2 canonical_title+author_id一致（自動採用） | {cnt['key']} |",
        f"| Tier 3 canonical_titleのみ一致（要レビュー） | {cnt['title']} |",
        f"| Tier 4 新規 work_id 採番 | {cnt['new']} |",
        f"| no_award / データ不完全 | {cnt['no_award'] + cnt['skip']} |",
        f"| 自動解決率 | {auto_matched / max(awarded_total,1) * 100:.1f}% |",
        f"",
    ]

    if dup_rows:
        lines += [
            f"## ⚠️ 要レビュー: duplicate_candidates.csv ({len(dup_rows)} 件)",
            f"",
            f"| incoming_title | incoming_author | candidate_work_id | matched_title | 理由 | 確信度 |",
            f"|---|---|---|---|---|---|",
        ]
        for d in dup_rows:
            lines.append(
                f"| {d['incoming_title']} | {d['incoming_author']} "
                f"| {d['candidate_work_id']} | {d['matched_title']} "
                f"| {d['match_reason']} | {d['confidence']} |"
            )
        lines += [
            f"",
            f"> 確認後、該当行の work_id を手動で設定し、"
            f"`plam_build_award_history.py` を再実行してください。",
        ]
    else:
        lines += [
            f"## ✅ 要レビューなし",
            f"",
            f"全作品が自動解決されました。",
        ]

    lines += [
        f"",
        f"## work_id 永久不変ルール",
        f"",
        f"- 既存 work_id は絶対に再採番しない",
        f"- 新規作品にのみ新しい work_id を採番する",
        f"- 重複判定で既存作品と一致した場合は既存 work_id を再利用する",
        f"- Tier 3 候補は人による確認を経てから work_id を設定する",
    ]

    MATCH_REPORT.write_text("\n".join(lines), encoding="utf-8")


# ── エントリーポイント ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PLAM V1.5 — works.csv アップグレード / 賞CSV インポート"
    )
    parser.add_argument("--upgrade", action="store_true",
                        help="works.csv を V1.5 形式に移行（canonical_title/author_id追加）")
    parser.add_argument("--import", dest="import_csv", metavar="CSV",
                        help="新しい賞 CSV を 4段階マッチングで取り込む")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込みを行わずに結果を表示する")
    args = parser.parse_args()

    if args.upgrade:
        cmd_upgrade(args.dry_run)
    elif args.import_csv:
        cmd_import(Path(args.import_csv), args.dry_run)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

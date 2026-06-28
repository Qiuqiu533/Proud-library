"""
PLAM Version 1.6 — 重複判定パイプライン + 運用ログ・統計

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
DUP_REVIEW_PATH = PLAM_DIR / "duplicate_review_history.csv"
IMPORT_LOG_PATH = PLAM_DIR / "award_import_log.csv"
REPORTS_DIR    = Path("reports")
MATCH_REPORT   = REPORTS_DIR / "work_matching_report.md"
STATISTICS_MD  = REPORTS_DIR / "statistics.md"

WORKS_FIELDS   = ["work_id", "canonical_title", "title", "author",
                  "author_id", "isbn13", "isbn_status", "notes"]
AUTHORS_FIELDS = ["author_id", "author_name", "author_name_kana",
                  "birth_year", "death_year", "notes"]
DUP_FIELDS     = ["candidate_work_id", "incoming_title", "matched_title",
                  "incoming_author", "matched_author",
                  "match_reason", "confidence", "source_csv"]
DUP_REVIEW_FIELDS = ["candidate_id", "candidate_work_id", "incoming_title",
                     "incoming_author", "decision", "review_date", "reviewer", "notes"]
IMPORT_LOG_FIELDS = ["import_id", "award_id", "import_date", "records_added",
                     "tier1_matches", "tier2_matches", "tier3_reviews", "tier4_new",
                     "reviewer", "commit_hash"]

EXCLUDE = {"awards_master.csv", "works.csv", "authors.csv",
           "aliases.csv", "award_history.csv",
           "duplicate_candidates.csv", "duplicate_review_history.csv",
           "award_import_log.csv"}


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
    # skip には「title/author 空欄」が含まれる。no_award 行は status=="no_award" のもの
    # だが title/author が空なので skip にも計上される場合があるため両方合計で表示
    no_skip_total = cnt["no_award"] + cnt["skip"]
    awarded_total = cnt["total"] - no_skip_total
    auto_matched  = cnt["isbn"] + cnt["key"]

    print(f"\n  総行数: {cnt['total']} 件（受賞対象: {awarded_total}件 / no_award+skip: {no_skip_total}件）")
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

        # award_import_log.csv
        _log_import(csv_path, cnt, awarded_total)  # awarded_total = total - no_award - skip
        print(f"  ✅ {IMPORT_LOG_PATH} に記録")

        # statistics.md
        _generate_statistics(works, authors)
        print(f"  ✅ {STATISTICS_MD}")

        # duplicate_review_history.csv（初回のみヘッダ作成）
        if not DUP_REVIEW_PATH.exists():
            write_csv(DUP_REVIEW_PATH, DUP_REVIEW_FIELDS, [])
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


# ── V1.6: award_import_log ──────────────────────────────────────────────────

def _log_import(csv_path: Path, cnt: dict, awarded_total: int) -> None:
    """取り込み結果を award_import_log.csv に追記する"""
    existing = read_csv(IMPORT_LOG_PATH) if IMPORT_LOG_PATH.exists() else []
    import_id = len(existing) + 1

    # award_id を CSV から推定（先頭の受賞行から取得）
    rows = read_csv(csv_path)
    award_id = next((r.get("award_id", "") for r in rows if r.get("award_id")), "UNKNOWN")

    existing.append({
        "import_id":    import_id,
        "award_id":     award_id,
        "import_date":  datetime.now().strftime("%Y-%m-%d"),
        "records_added": awarded_total,
        "tier1_matches": cnt["isbn"],
        "tier2_matches": cnt["key"],
        "tier3_reviews": cnt["title"],
        "tier4_new":    cnt["new"],
        "reviewer":     "",
        "commit_hash":  "",
    })
    write_csv(IMPORT_LOG_PATH, IMPORT_LOG_FIELDS, existing)


# ── V1.6: statistics.md ─────────────────────────────────────────────────────

def _generate_statistics(works: WorkRegistry, authors: AuthorRegistry) -> None:
    """reports/statistics.md を再生成する"""
    REPORTS_DIR.mkdir(exist_ok=True)

    history = read_csv(PLAM_DIR / "award_history.csv") if (PLAM_DIR / "award_history.csv").exists() else []

    # 複数受賞
    from collections import Counter, defaultdict
    work_award_cnt = Counter(r["work_id"] for r in history if r.get("work_id"))
    multi_award = sum(1 for c in work_award_cnt.values() if c > 1)

    # 信頼性別件数
    conf_cnt: dict[str, int] = Counter(r.get("confidence", "REVIEWED") for r in history)
    official_rate = conf_cnt.get("OFFICIAL", 0) / max(len(history), 1) * 100

    # ISBN付与率
    total_works = len(works.rows)
    isbn_count  = sum(1 for r in works.rows if (r.get("isbn13") or "").strip())
    isbn_rate   = isbn_count / total_works * 100 if total_works else 0

    # レビュー待ち
    dup_pending = len(read_csv(DUP_PATH)) if DUP_PATH.exists() else 0

    # 賞別集計
    award_files = sorted(p for p in PLAM_DIR.glob("*.csv") if p.name not in EXCLUDE)
    award_stats: list[dict] = []
    seen_award_ids: set[str] = set()
    for p in award_files:
        rows = read_csv(p)
        if not rows or "award_id" not in rows[0]:
            continue
        aid   = rows[0].get("award_id", "")
        aname = rows[0].get("award_name", aid)
        if aid in seen_award_ids:
            continue
        seen_award_ids.add(aid)
        rounds   = len({r.get("award_no") for r in rows if r.get("award_no")})
        awarded  = sum(1 for r in rows if r.get("status") != "no_award"
                       and r.get("work_id", "").startswith("PLAM-"))
        award_stats.append({"id": aid, "name": aname, "rounds": rounds, "awarded": awarded})

    import_log = read_csv(IMPORT_LOG_PATH) if IMPORT_LOG_PATH.exists() else []

    lines = [
        f"# PLAM Statistics",
        f"",
        f"更新日時: {datetime.now():%Y-%m-%d %H:%M}",
        f"",
        f"## データ規模",
        f"",
        f"| 項目 | 件数 |",
        f"|---|---|",
        f"| 作品数 | {total_works} |",
        f"| 著者数 | {len(authors.rows)} |",
        f"| 賞数 | {len(seen_award_ids)} |",
        f"| 受賞履歴数 | {len(history)} |",
        f"",
        f"## 品質指標",
        f"",
        f"| 指標 | 値 |",
        f"|---|---|",
        f"| 複数受賞作品数 | {multi_award} |",
        f"| ISBN付与率 | {isbn_rate:.1f}% |",
        f"| 公式ソース率 (OFFICIAL) | {official_rate:.1f}% |",
        f"| Tier3レビュー待ち件数 | {dup_pending} |",
        f"",
        f"## 賞別データ",
        f"",
        f"| 賞ID | 賞名 | 回次数 | 受賞作品数 |",
        f"|---|---|---|---|",
    ]
    for s in award_stats:
        lines.append(f"| {s['id']} | {s['name']} | {s['rounds']} | {s['awarded']} |")

    lines += [
        f"",
        f"## 取り込み履歴",
        f"",
        f"| ID | 賞 | 日付 | 追加数 | Tier1 | Tier2 | Tier3 | Tier4(新規) |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for lg in import_log:
        lines.append(
            f"| {lg['import_id']} | {lg['award_id']} | {lg['import_date']} "
            f"| {lg['records_added']} | {lg['tier1_matches']} "
            f"| {lg['tier2_matches']} | {lg['tier3_reviews']} | {lg['tier4_new']} |"
        )

    STATISTICS_MD.write_text("\n".join(lines), encoding="utf-8")

    # V1.7: cross_award_summary.csv と award_overlap.md を更新
    _generate_cross_award_summary(history)
    _generate_award_overlap(history, [s["id"] for s in award_stats])

    # V1.8: award_network.csv / author_award_summary.csv / overlap_trend.md を更新
    _generate_award_network(history, [s["id"] for s in award_stats])
    _generate_author_award_summary(history)
    _generate_overlap_trend(import_log, history)

    # V1.9: award_graph.csv / award_author_graph.csv / statistics_history.csv を更新
    _generate_award_graph(history, [s["id"] for s in award_stats])
    _generate_award_author_graph(history)
    from collections import Counter as _Counter
    work_award_cnt = _Counter(r["work_id"] for r in history if r.get("work_id"))
    multi_cnt = sum(1 for c in work_award_cnt.values() if c > 1)
    _append_statistics_history(
        works_count=total_works, award_count=len(seen_award_ids),
        history_count=len(history), multi_count=multi_cnt,
        author_count=len(authors.rows)
    )


# ── V1.7: cross_award_summary.csv ───────────────────────────────────────────

CROSS_SUMMARY_PATH = PLAM_DIR / "cross_award_summary.csv"
CROSS_SUMMARY_FIELDS = ["work_id", "title", "author", "award_count",
                         "awards", "first_award_year", "latest_award_year"]
AWARD_OVERLAP_MD = REPORTS_DIR / "award_overlap.md"


def _generate_cross_award_summary(history: list[dict]) -> None:
    """複数受賞作品の一覧 cross_award_summary.csv を生成する"""
    works = read_csv(WORKS_PATH)
    works_map = {r["work_id"]: r for r in works if r.get("work_id")}

    from collections import defaultdict
    work_hist: dict[str, list[dict]] = defaultdict(list)
    for r in history:
        wid = r.get("work_id", "").strip()
        if wid:
            work_hist[wid].append(r)

    summary_rows = []
    for wid, rows in sorted(work_hist.items()):
        awards = sorted({r["award_id"] for r in rows})
        years  = [int(r["award_year"]) for r in rows if r.get("award_year", "").isdigit()]
        w = works_map.get(wid, {})
        summary_rows.append({
            "work_id":          wid,
            "title":            w.get("title", ""),
            "author":           w.get("author", ""),
            "award_count":      len(awards),
            "awards":           ",".join(awards),
            "first_award_year": min(years) if years else "",
            "latest_award_year": max(years) if years else "",
        })

    # award_count > 1 のみ cross_award_summary に書く（単受賞は除外）
    multi = [r for r in summary_rows if r["award_count"] > 1]
    write_csv(CROSS_SUMMARY_PATH, CROSS_SUMMARY_FIELDS, multi)


def _generate_award_overlap(history: list[dict], award_ids: list[str]) -> None:
    """各賞ペアの重複作品数を award_overlap.md に書き出す"""
    from collections import defaultdict
    work_awards: dict[str, set[str]] = defaultdict(set)
    for r in history:
        wid = r.get("work_id", "").strip()
        aid = r.get("award_id", "").strip()
        if wid and aid:
            work_awards[wid].add(aid)

    lines = [
        f"# PLAM 賞別重複分析（award_overlap.md）",
        f"",
        f"生成日時: {datetime.now():%Y-%m-%d %H:%M}",
        f"",
        f"## 賞ペア別 重複作品数",
        f"",
        f"| 賞A | 賞B | 重複作品数 | 作品 |",
        f"|---|---|---|---|",
    ]

    ids = sorted(set(award_ids))
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            overlaps = [wid for wid, awards in work_awards.items()
                        if a in awards and b in awards]
            # 作品タイトル（先頭3件まで）
            works = read_csv(WORKS_PATH)
            works_map = {r["work_id"]: r.get("title", "") for r in works}
            titles = ", ".join(works_map.get(w, w) for w in overlaps[:3])
            if len(overlaps) > 3:
                titles += f" 他{len(overlaps)-3}件"
            lines.append(f"| {a} | {b} | {len(overlaps)} | {titles} |")

    lines += [
        f"",
        f"## 複数受賞作品一覧",
        f"",
        f"| work_id | タイトル | 著者 | 受賞賞 | 初受賞年 | 最終受賞年 |",
        f"|---|---|---|---|---|---|",
    ]
    cross = read_csv(CROSS_SUMMARY_PATH) if CROSS_SUMMARY_PATH.exists() else []
    for r in cross:
        lines.append(
            f"| {r['work_id']} | {r['title']} | {r['author']} "
            f"| {r['awards']} | {r['first_award_year']} | {r['latest_award_year']} |"
        )

    AWARD_OVERLAP_MD.write_text("\n".join(lines), encoding="utf-8")


# ── V1.8: award_network / author_award_summary / overlap_trend ───────────────

AWARD_NETWORK_PATH   = PLAM_DIR / "award_network.csv"
AWARD_NETWORK_FIELDS = ["award_a", "award_b", "overlap_count", "titles"]
AUTHOR_SUMMARY_PATH  = PLAM_DIR / "author_award_summary.csv"
AUTHOR_SUMMARY_FIELDS= ["author_id", "author", "work_count", "award_count", "awards"]
OVERLAP_TREND_MD     = REPORTS_DIR / "overlap_trend.md"


def _generate_award_network(history: list[dict], award_ids: list[str]) -> None:
    """賞ペア別重複数を award_network.csv に書き出す"""
    from collections import defaultdict
    work_awards: dict[str, set[str]] = defaultdict(set)
    for r in history:
        wid = r.get("work_id", "").strip()
        aid = r.get("award_id", "").strip()
        if wid and aid:
            work_awards[wid].add(aid)

    works_map = {r["work_id"]: r.get("title", "") for r in read_csv(WORKS_PATH)}
    ids = sorted(set(award_ids))
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            overlaps = [wid for wid, awards in work_awards.items()
                        if a in awards and b in awards]
            titles = "|".join(works_map.get(w, w) for w in overlaps[:5])
            rows.append({"award_a": a, "award_b": b,
                         "overlap_count": len(overlaps), "titles": titles})
    write_csv(AWARD_NETWORK_PATH, AWARD_NETWORK_FIELDS, rows)


def _generate_author_award_summary(history: list[dict]) -> None:
    """著者単位の受賞集計を author_award_summary.csv に書き出す"""
    from collections import defaultdict
    works_map = {r["work_id"]: r for r in read_csv(WORKS_PATH) if r.get("work_id")}

    # work_id → (author_id, author_name) のマップ
    wid_to_author: dict[str, tuple[str, str]] = {}
    for wid, w in works_map.items():
        wid_to_author[wid] = (w.get("author_id", ""), w.get("author", ""))

    # 著者ごとに work_id と award_id を集計
    author_works: dict[str, set[str]] = defaultdict(set)
    author_awards: dict[str, set[str]] = defaultdict(set)
    author_name_map: dict[str, str] = {}

    for r in history:
        wid = r.get("work_id", "").strip()
        aid = r.get("award_id", "").strip()
        if not wid or not aid:
            continue
        author_id, author_name = wid_to_author.get(wid, ("", ""))
        if not author_id:
            continue
        author_works[author_id].add(wid)
        author_awards[author_id].add(aid)
        author_name_map[author_id] = author_name

    rows = []
    for author_id in sorted(author_awards, key=lambda x: -len(author_awards[x])):
        rows.append({
            "author_id":   author_id,
            "author":      author_name_map.get(author_id, ""),
            "work_count":  len(author_works[author_id]),
            "award_count": len(author_awards[author_id]),
            "awards":      ",".join(sorted(author_awards[author_id])),
        })
    write_csv(AUTHOR_SUMMARY_PATH, AUTHOR_SUMMARY_FIELDS, rows)


def _generate_overlap_trend(import_log: list[dict], history: list[dict]) -> None:
    """取り込みごとの重複率を reports/overlap_trend.md に書き出す"""
    from collections import defaultdict

    # 全 work_id の出現賞を集計
    work_awards: dict[str, set[str]] = defaultdict(set)
    for r in history:
        wid = r.get("work_id", "").strip()
        aid = r.get("award_id", "").strip()
        if wid and aid:
            work_awards[wid].add(aid)

    lines = [
        "# PLAM 重複トレンドレポート（overlap_trend.md）",
        "",
        f"生成日時: {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "## 取り込み別 重複率",
        "",
        "| 賞ID | 取り込み日 | 追加数 | Tier2(重複) | 重複率 |",
        "|---|---|---|---|---|",
    ]
    for lg in import_log:
        added   = int(lg.get("records_added", 0) or 0)
        tier2   = int(lg.get("tier2_matches", 0) or 0)
        rate    = tier2 / added * 100 if added > 0 else 0.0
        lines.append(
            f"| {lg['award_id']} | {lg['import_date']} "
            f"| {added} | {tier2} | {rate:.1f}% |"
        )

    # 複数受賞が多い著者トップ5（author_award_summary.csvから）
    author_summary = read_csv(AUTHOR_SUMMARY_PATH) if AUTHOR_SUMMARY_PATH.exists() else []
    multi_authors = [r for r in author_summary if int(r.get("award_count", 0) or 0) > 1]

    lines += [
        "",
        "## 複数賞受賞著者（上位10名）",
        "",
        "| 著者 | 受賞賞数 | 受賞賞 |",
        "|---|---|---|",
    ]
    for r in multi_authors[:10]:
        lines.append(f"| {r['author']} | {r['award_count']} | {r['awards']} |")

    OVERLAP_TREND_MD.write_text("\n".join(lines), encoding="utf-8")


# ── V1.9: award_graph / award_author_graph / statistics_history ───────────────

AWARD_GRAPH_PATH        = PLAM_DIR / "award_graph.csv"
AWARD_GRAPH_FIELDS      = ["award_from", "award_to", "overlap_count", "work_ids"]
AUTHOR_GRAPH_PATH       = PLAM_DIR / "award_author_graph.csv"
AUTHOR_GRAPH_FIELDS     = ["author_id", "author", "award_sequence", "award_years"]
STATS_HISTORY_PATH      = REPORTS_DIR / "statistics_history.csv"
STATS_HISTORY_FIELDS    = ["snapshot_date", "version_tag", "works", "awards",
                            "histories", "multi_award_works", "authors"]


def _generate_award_graph(history: list[dict], award_ids: list[str]) -> None:
    """有向賞ペアグラフを award_graph.csv に書き出す（相互記録）"""
    from collections import defaultdict
    work_awards: dict[str, set[str]] = defaultdict(set)
    for r in history:
        wid = r.get("work_id", "").strip()
        aid = r.get("award_id", "").strip()
        if wid and aid:
            work_awards[wid].add(aid)

    ids = sorted(set(award_ids))
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            shared = [wid for wid, awards in work_awards.items()
                      if a in awards and b in awards]
            if shared:
                work_ids_str = "|".join(shared)
                rows.append({"award_from": a, "award_to": b,
                             "overlap_count": len(shared), "work_ids": work_ids_str})
                rows.append({"award_from": b, "award_to": a,
                             "overlap_count": len(shared), "work_ids": work_ids_str})
    write_csv(AWARD_GRAPH_PATH, AWARD_GRAPH_FIELDS, rows)


def _generate_award_author_graph(history: list[dict]) -> None:
    """著者ごとの受賞賞系列を award_author_graph.csv に書き出す（時系列順）"""
    from collections import defaultdict
    works_map = {r["work_id"]: r for r in read_csv(WORKS_PATH) if r.get("work_id")}
    wid_to_author: dict[str, tuple[str, str]] = {
        wid: (w.get("author_id", ""), w.get("author", ""))
        for wid, w in works_map.items()
    }

    # 著者ごとに (award_year, award_id) を収集
    author_timeline: dict[str, list[tuple[int, str]]] = defaultdict(list)
    author_name_map: dict[str, str] = {}
    for r in history:
        wid = r.get("work_id", "").strip()
        aid = r.get("award_id", "").strip()
        yr_str = r.get("award_year", "")
        if not wid or not aid or not yr_str.isdigit():
            continue
        author_id, author_name = wid_to_author.get(wid, ("", ""))
        if not author_id:
            continue
        author_timeline[author_id].append((int(yr_str), aid))
        author_name_map[author_id] = author_name

    rows = []
    for author_id, timeline in sorted(author_timeline.items()):
        # 重複除去・時系列ソート
        seen: set[str] = set()
        ordered: list[tuple[int, str]] = []
        for yr, aid in sorted(timeline):
            if aid not in seen:
                seen.add(aid)
                ordered.append((yr, aid))
        if len(ordered) < 2:
            continue  # 複数賞受賞著者のみ記録
        sequence = "→".join(a for _, a in ordered)
        years    = "|".join(str(y) for y, _ in ordered)
        rows.append({
            "author_id":      author_id,
            "author":         author_name_map.get(author_id, ""),
            "award_sequence": sequence,
            "award_years":    years,
        })
    write_csv(AUTHOR_GRAPH_PATH, AUTHOR_GRAPH_FIELDS, rows)


def _append_statistics_history(works_count: int, award_count: int,
                                history_count: int, multi_count: int,
                                author_count: int) -> None:
    """statistics_history.csv にスナップショットを追記する"""
    REPORTS_DIR.mkdir(exist_ok=True)
    existing = read_csv(STATS_HISTORY_PATH) if STATS_HISTORY_PATH.exists() else []
    today = datetime.now().strftime("%Y-%m-%d")
    # 同日のスナップショットは上書き
    existing = [r for r in existing if r.get("snapshot_date") != today]
    existing.append({
        "snapshot_date":    today,
        "version_tag":      f"v1.9+{award_count}awards",
        "works":            works_count,
        "awards":           award_count,
        "histories":        history_count,
        "multi_award_works": multi_count,
        "authors":          author_count,
    })
    write_csv(STATS_HISTORY_PATH, STATS_HISTORY_FIELDS, existing)


# ── エントリーポイント ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PLAM V1.5 — works.csv アップグレード / 賞CSV インポート"
    )
    parser.add_argument("--upgrade", action="store_true",
                        help="works.csv を V1.5 形式に移行（canonical_title/author_id追加）")
    parser.add_argument("--import", dest="import_csv", metavar="CSV",
                        help="新しい賞 CSV を 4段階マッチングで取り込む")
    parser.add_argument("--stats", action="store_true",
                        help="statistics.md を現在の状態で再生成する")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込みを行わずに結果を表示する")
    args = parser.parse_args()

    if args.upgrade:
        cmd_upgrade(args.dry_run)
    elif args.import_csv:
        cmd_import(Path(args.import_csv), args.dry_run)
    elif args.stats:
        works   = WorkRegistry(); works.load()
        authors = AuthorRegistry(); authors.load()
        _generate_statistics(works, authors)
        print(f"✅ {STATISTICS_MD} 更新完了")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

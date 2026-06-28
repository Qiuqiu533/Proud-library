# PLAM Version 1.2 設計仕様

**Proud Library Award Master（PLAM）**
最終更新: 2026-06-28

---

## 基本方針：作品中心（work-centric）モデル

1作品 → 複数の賞を受賞可能  
`work_id` は作品の永続識別子（賞・ISBN・版に依存しない）

---

## ID体系

| ID | 形式 | 役割 | 変更可否 |
|---|---|---|---|
| `work_id` | `PLAM-000001` | 作品共通ID（賞横断） | **変更禁止** |
| `entry_id` | `AKU-001-H1-01` | 賞CSV内のレコード識別子 | 変更禁止 |
| `award_id` | `AKU`, `NAO`, ... | 賞の識別子 | 変更禁止 |

### work_id 採番ルール
- 連番: `PLAM-000001` 〜 `PLAM-999999`
- `no_award` レコードは `work_id` を持たない（空欄）
- 同一作品（title + author が一致）は同一 `work_id` を共有
- ISBN変更・改題が発生しても `work_id` は変更しない

---

## CSV構造（Version 1.2）

### 賞別CSV（例: akutagawa_prize.csv）

```
entry_id,work_id,award_id,award_name,award_year,award_no,award_term,
title,author,isbn13,isbn_status,status,remarks
```

- `entry_id`: 賞CSV内の一意なレコードID（旧 work_id を改名）
- `work_id`: 作品共通ID（no_award は空欄）

### works.csv（作品マスター）

```
work_id,title,author,isbn13,isbn_status,notes
```

- 賞別CSVから自動生成
- 同一作品の重複なし

---

## テーブル設計（DB実装時）

```sql
-- 作品マスター
CREATE TABLE works (
    work_id     TEXT PRIMARY KEY,   -- PLAM-000001
    title       TEXT NOT NULL,
    author      TEXT NOT NULL,
    isbn13      TEXT,
    isbn_status TEXT DEFAULT 'missing',
    notes       TEXT
);

-- 賞マスター
CREATE TABLE awards (
    award_id    TEXT PRIMARY KEY,   -- AKU
    award_name  TEXT NOT NULL,
    category    TEXT,
    source_name TEXT,
    source_url  TEXT
);

-- 受賞履歴（中間テーブル）
CREATE TABLE award_history (
    history_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id     TEXT NOT NULL REFERENCES works(work_id),
    award_id    TEXT NOT NULL REFERENCES awards(award_id),
    award_year  INTEGER NOT NULL,
    award_no    INTEGER,
    award_term  TEXT,               -- H1 / H2
    entry_id    TEXT,               -- 元CSVのentry_id
    status      TEXT NOT NULL,      -- awarded / co_winner
    remarks     TEXT
);

-- no_award記録（worksと無関係）
CREATE TABLE award_no_records (
    award_id    TEXT NOT NULL,
    award_year  INTEGER NOT NULL,
    award_no    INTEGER,
    award_term  TEXT
);
```

---

## 複数受賞の例

```
works:
  PLAM-001850  黒牢城  米澤穂信

award_history:
  PLAM-001850  NAO  2022  166  H2  awarded
  PLAM-001850  HOK  2022  22   -   awarded
  PLAM-001850  JRM  2023  76   -   awarded
  PLAM-001850  HMI  2023  -    -   awarded
```

→ 作品詳細画面で「受賞歴」を一覧表示可能

---

## ファイル構成

```
data/plam/
  DESIGN.md                    ← 本ファイル
  awards_master.csv            ← 賞マスター
  works.csv                    ← 作品マスター（自動生成）
  akutagawa_prize.csv          ← 芥川賞（entry_id + work_id）
  naoki_prize.csv              ← 直木賞（entry_id + work_id）
  metadata/
    AKU.json
    NAO.json
    ...
  reports/
    phase1_report.md
    phase2_report.md
    phase3_report.md
    ...
```

---

## スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/plam_validate.py` | 各CSVの品質検証 |
| `scripts/plam_assign_work_ids.py` | work_idを採番してworks.csvを生成 |
| `scripts/cross_award_validate.py` | 賞横断の整合性検証 |
| `scripts/import_plam.py` | CSVからDBへインポート（将来） |

---

## 品質ルール

1. `work_id` は一度採番したら変更禁止
2. DBへの直接編集禁止（CSV → スクリプト → DB）
3. 各Phase完了後に `plam_validate.py` + `cross_award_validate.py` を実行してからコミット
4. ISBNはPhase ISBNで一括付与（各Phase作業中は `missing` のまま）

# PLAM — Proud Library Award Master

**A knowledge graph and analytics platform for Japanese literary awards.**

PLAMは日本主要文学賞の受賞作品データを正確に構築し、賞間の関係性・クラスタ構造・著者キャリアを定量的に分析するためのデータ基盤です。Proud Library（プラウド船橋コミュニティ図書館）の推薦・検索・分析機能を支えます。

---

## 収録賞（11賞 / 782作品 / 821受賞履歴）

| award_id | 賞名 | 種別 | 創設 | weight |
|---|---|---|---|---|
| AKU | 芥川賞 | literary_work | 1935 | 100 |
| NAO | 直木賞 | literary_work | 1935 | 95 |
| JRA | 日本推理作家協会賞 | professional | 1948 | 92 |
| HKM | 本格ミステリ大賞 | critic | 2001 | 90 |
| KIK | 吉川英治文学賞 | career | 1967 | 88 |
| HON | 本屋大賞 | reader_vote | 2004 | 85 |
| JSF | 日本SF大賞 | professional | 1980 | 85 |
| YAM | 山本周五郎賞 | entertainment | 1988 | 82 |
| KMS | このミステリーがすごい！ | ranking | 1988 | 80 |
| RAN | 江戸川乱歩賞 | debut | 1954 | 75 |
| HOR | 日本ホラー小説大賞 | debut | 1994 | 72 |

---

## ファイル構成

### コアデータ
| ファイル | 内容 |
|---|---|
| `works.csv` | 作品マスター（work_id / canonical_title / author / isbn13） |
| `authors.csv` | 著者マスター（author_id / name） |
| `award_history.csv` | 受賞履歴（全賞横断） |
| `awards_master.csv` | 賞マスター（award_type / weight / founded） |

### 賞データ
| ファイル | 賞 |
|---|---|
| `akutagawa_prize.csv` | 芥川賞 |
| `naoki_prize.csv` | 直木賞 |
| `jra_prize.csv` | 日本推理作家協会賞 |
| `honkaku_mystery_prize.csv` | 本格ミステリ大賞 |
| `yoshikawa_prize.csv` | 吉川英治文学賞 |
| `honnya_prize.csv` | 本屋大賞 |
| `jsf_prize.csv` | 日本SF大賞 |
| `yamamoto_prize.csv` | 山本周五郎賞 |
| `konomi_prize.csv` | このミステリーがすごい！国内編 |
| `ranpo_prize.csv` | 江戸川乱歩賞 |
| `horror_prize.csv` | 日本ホラー小説大賞 |

### 分析データ（自動生成）
| ファイル | 内容 | 生成スクリプト |
|---|---|---|
| `award_similarity.csv` | 賞間Jaccard係数（55ペア） | `plam_build_v20.py --similarity` |
| `graph_data.csv` | ネットワークグラフ用エッジデータ | `plam_build_v20.py --graph` |
| `cluster_summary.csv` | 賞クラスタ定義（5クラスタ） | 手動定義 |
| `bridge_works.csv` | クラスタ横断作品（34作品） | `plam_build_v20.py --bridge` |
| `award_network.csv` | 賞ペア別重複数 | `plam_build_v15.py --stats` |
| `author_award_summary.csv` | 著者別受賞集計 | `plam_build_v15.py --stats` |
| `award_graph.csv` | 有向グラフ（双方向記録） | `plam_build_v15.py --stats` |
| `award_author_graph.csv` | 著者賞受賞系列 | `plam_build_v15.py --stats` |

---

## クラスタ構造

データ分析（Jaccard係数）から4クラスタが定量的に確認されています：

```
【ミステリ評価クラスタ】 max Jaccard: 0.133
  HKM ──0.133── KMS
   │                │
  0.063            0.068
   │                │
  JRA ──0.050── YAM
  └── RAN（乱歩賞・新人入口）

【文芸・読者クラスタ】 max Jaccard: 0.012
  AKU  NAO ──0.012── YAM（ミステリクラスタとの橋渡し）
              └── HON

【SF独立クラスタ】
  JSF（全賞とのJaccard ≤ 0.010）

【ホラー独立クラスタ】
  HOR（全賞とのJaccard ≤ 0.017）

【キャリア評価クラスタ】
  KIK（全賞とのJaccard = 0.000）
```

---

## 主要知見

- **HKM ↔ KMS = 0.133** — PLAMで最も評価軸が近い賞ペア（ミステリ専門家評価群の核心）
- **KIK = 0.000** — キャリア評価型賞は作品重複が皆無（同著者でも別作品を評価）
- **AKU = 0.000** — 純文学は全ミステリ賞と重複なし（評価軸の独立性）
- **JSF・HOR = ≤ 0.017** — SF・ホラーは独立クラスタを形成
- **cross_cluster bridge works: 12件** — 黒牢城（literary×mystery）、アラビアの夜の種族（mystery×sf）等

---

## スクリプト一覧

```bash
# インポートパイプライン（新賞追加時）
python3 scripts/plam_build_v15.py --import data/plam/<award>.csv
python3 scripts/plam_build_award_history.py
python3 scripts/cross_award_validate.py
python3 scripts/plam_build_v15.py --stats

# 分析データ再生成
python3 scripts/plam_build_v20.py --similarity   # Jaccard係数
python3 scripts/plam_build_v20.py --graph        # ネットワークエッジ
python3 scripts/plam_build_v20.py --bridge       # bridge_works
python3 scripts/plam_build_v20.py --validate-master  # マスター照合

# テスト
python3 -m pytest tests/ -q
```

---

## バージョン履歴

| バージョン | 内容 |
|---|---|
| v1.0–1.4 | AKU/NAO/HON/RAN インポート・基本マッチング |
| v1.5 | 4段階マッチング（Tier 1〜4）・work_id永久不変ルール |
| v1.7 | cross_award_summary / award_overlap |
| v1.8 | award_network / author_award_summary / overlap_trend |
| v1.9 | award_graph / award_author_graph / statistics_history |
| **v2.0** | **awards_master（award_type/weight）/ award_similarity（Jaccard）** |
| **v2.1** | **graph_data / JSF（日本SF大賞）インポート** |
| **v2.2** | **cluster_summary / bridge_works / HOR（日本ホラー小説大賞）インポート** |

---

*詳細な分析知見は [docs/PLAM_INSIGHTS.md](../docs/PLAM_INSIGHTS.md) を参照。*

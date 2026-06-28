# PLAM work_matching_report.md

生成日時: 2026-06-29 07:58
インポート対象: `horror_prize.csv`

## サマリー

| 項目 | 件数 |
|---|---|
| 処理対象（受賞行） | 14 |
| Tier 1 ISBN一致（自動確定） | 0 |
| Tier 2 canonical_title+author_id一致（自動採用） | 1 |
| Tier 3 canonical_titleのみ一致（要レビュー） | 0 |
| Tier 4 新規 work_id 採番 | 13 |
| no_award / データ不完全 | 12 |
| 自動解決率 | 7.1% |

## ✅ 要レビューなし

全作品が自動解決されました。

## work_id 永久不変ルール

- 既存 work_id は絶対に再採番しない
- 新規作品にのみ新しい work_id を採番する
- 重複判定で既存作品と一致した場合は既存 work_id を再利用する
- Tier 3 候補は人による確認を経てから work_id を設定する
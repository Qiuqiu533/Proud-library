"""
直木賞 Phase4 award_no 修正スクリプト

問題: Phase4 NAOデータの award_no が公式より1小さい
  例) 私のデータ 142回(2009H2)=佐々木譲 → 公式サイト: 143回(2009H2)
  Phase4全行 (award_no=113〜142) に +1 が必要

修正後:
  113→114, 114→115, ... 142→143
  entry_id: NAO-113-xxx → NAO-114-xxx

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_fix_nao_phase4_nos.py [--dry-run]
"""
import argparse, csv, re
from pathlib import Path

NAO_PATH = Path("data/plam/naoki_prize.csv")


def read_raw_rows(path: Path) -> tuple[list[str], list[dict], list[str]]:
    """コメント行・ヘッダー・データ行を分離して返す"""
    comment_lines = []
    data_lines = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                comment_lines.append(line)
            else:
                data_lines.append(line)
    reader = csv.DictReader(data_lines)
    fieldnames = reader.fieldnames or []
    rows = list(reader)
    return comment_lines, rows, fieldnames


def fix_entry_id(eid: str) -> str:
    """NAO-NNN-TT-NN 形式の award_no部分に +1 を適用"""
    m = re.match(r"^(NAO-)(\d{3})(-\w{2}-\d{2})$", eid)
    if not m:
        return eid
    prefix, no_str, suffix = m.groups()
    new_no = int(no_str) + 1
    return f"{prefix}{new_no:03d}{suffix}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    comment_lines, rows, fieldnames = read_raw_rows(NAO_PATH)

    fixed = 0
    new_rows = []
    for r in rows:
        award_no = r.get("award_no", "").strip()
        if not award_no:
            new_rows.append(r)
            continue
        try:
            no = int(award_no)
        except ValueError:
            new_rows.append(r)
            continue

        if no >= 113:  # Phase4以降を修正
            new_r = dict(r)
            new_r["award_no"] = str(no + 1)
            # entry_id も更新
            old_eid = new_r.get("entry_id", "")
            if old_eid:
                new_r["entry_id"] = fix_entry_id(old_eid)
            new_rows.append(new_r)
            fixed += 1
        else:
            new_rows.append(r)

    print(f"修正対象: {fixed} 行 (Phase4: award_no 113〜142 → 114〜143)")

    if not args.dry_run:
        with open(NAO_PATH, "w", encoding="utf-8", newline="") as f:
            for c in comment_lines:
                f.write(c)
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(new_rows)
        print(f"✅ {NAO_PATH} 修正完了")
    else:
        # dry-run: 変更前後を5件表示
        print("\n[dry-run] 変更サンプル:")
        sample_count = 0
        for old, new in zip(rows, new_rows):
            if old.get("award_no") != new.get("award_no") and sample_count < 5:
                print(f"  {old['entry_id']} award_no:{old['award_no']} → {new['entry_id']} award_no:{new['award_no']}")
                sample_count += 1


if __name__ == "__main__":
    main()

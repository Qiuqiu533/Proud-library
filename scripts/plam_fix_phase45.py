"""
PLAM Phase4/5 包括修正スクリプト

問題:
1. Phase4 NAO award_no を誤って+1した → -1して元に戻す (113-142が正しい)
2. Phase5 NAO award_no が+1ずれている → -1修正 (144→143, ..., 175→174)
3. AKU Phase5 に 173回(2025H1 no_award)・174回(2025H2)を追加
4. AKU 171回 著者「松永K三郎」→ 正式表記「松永K」に修正

公式確認:
  芥川賞: 143(2010H1)=赤染晶子, 174(2025H2)=鳥山まこと/畠山丑雄
  直木賞: 113(1995H1)=赤瀬川隼, 142(2009H2)=佐々木譲, 143(2010H1)=中島京子, 174(2025H2)=嶋津輝
  情報源: 公益財団法人日本文学振興会 2026-06-28確認

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_fix_phase45.py [--dry-run]
"""
from __future__ import annotations
import argparse, csv, re
from pathlib import Path

AKU_PATH = Path("data/plam/akutagawa_prize.csv")
NAO_PATH = Path("data/plam/naoki_prize.csv")


def read_csv(path: Path) -> tuple[list[str], list[dict], list[str]]:
    comments = []
    data_lines = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                comments.append(line)
            else:
                data_lines.append(line)
    reader = csv.DictReader(data_lines)
    return comments, list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, comments: list[str], fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        for c in comments:
            f.write(c)
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fix_entry_id(eid: str, prefix: str, delta: int) -> str:
    """entry_id の award_no 部分を delta 分ずらす"""
    m = re.match(rf"^({re.escape(prefix)})(\d{{3}})(-\w{{2}}-\d{{2}})$", eid)
    if not m:
        return eid
    p, no_str, suffix = m.groups()
    return f"{p}{int(no_str)+delta:03d}{suffix}"


# ── AKU 追加行 (2025年) ──────────────────────────────────────────────
AKU_2025 = [
    {"entry_id":"AKU-173-H1-00","work_id":"","award_id":"AKU","award_name":"芥川賞",
     "award_year":"2025","award_no":"173","award_term":"H1",
     "title":"","author":"","isbn13":"","isbn_status":"missing","status":"no_award","remarks":""},
    {"entry_id":"AKU-174-H2-01","work_id":"","award_id":"AKU","award_name":"芥川賞",
     "award_year":"2025","award_no":"174","award_term":"H2",
     "title":"時の家","author":"鳥山まこと","isbn13":"","isbn_status":"missing","status":"co_winner","remarks":""},
    {"entry_id":"AKU-174-H2-02","work_id":"","award_id":"AKU","award_name":"芥川賞",
     "award_year":"2025","award_no":"174","award_term":"H2",
     "title":"叫び","author":"畠山丑雄","isbn13":"","isbn_status":"missing","status":"co_winner","remarks":""},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # ── NAO 修正 (Phase4+5 全行を -1) ──────────────────────────────
    nao_comments, nao_rows, nao_fields = read_csv(NAO_PATH)
    nao_fixed = 0
    new_nao = []
    for r in nao_rows:
        try:
            no = int(r.get("award_no", ""))
        except ValueError:
            new_nao.append(r)
            continue

        if no >= 114:  # Phase4修正後(114-143) + Phase5(144-175) → 全て-1
            nr = dict(r)
            nr["award_no"] = str(no - 1)
            eid = nr.get("entry_id", "")
            if eid:
                nr["entry_id"] = fix_entry_id(eid, "NAO-", -1)
            new_nao.append(nr)
            nao_fixed += 1
        else:
            new_nao.append(r)

    print(f"NAO 修正: {nao_fixed} 行 (award_no -1)")
    if not args.dry_run:
        write_csv(NAO_PATH, nao_comments, nao_fields, new_nao)
        print(f"✅ {NAO_PATH} 更新完了")

    # ── AKU 修正 ────────────────────────────────────────────────────
    aku_comments, aku_rows, aku_fields = read_csv(AKU_PATH)

    # 1. 著者名修正: 松永K三郎 → 松永K
    aku_author_fixed = 0
    for r in aku_rows:
        if r.get("author") == "松永K三郎":
            r["author"] = "松永K"
            aku_author_fixed += 1

    # 2. 2025年データ追加
    if not args.dry_run:
        write_csv(AKU_PATH, aku_comments, aku_fields, aku_rows)
        # 追記
        with open(AKU_PATH, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=aku_fields)
            writer.writerows(AKU_2025)
        print(f"✅ {AKU_PATH} 著者名修正{aku_author_fixed}件・2025年3行追加")
    else:
        print(f"[dry-run] AKU: 著者名修正{aku_author_fixed}件、2025年3行追加予定")

    # ── NAO 修正確認サンプル ────────────────────────────────────────
    if args.dry_run:
        print("\n[dry-run] NAO 変更サンプル:")
        cnt = 0
        for old, new in zip(nao_rows, new_nao):
            if old.get("award_no") != new.get("award_no") and cnt < 5:
                print(f"  {old['entry_id']:20} award_no:{old['award_no']} → {new['entry_id']:20} award_no:{new['award_no']}")
                cnt += 1
        print(f"\n  NAO 末尾(修正後): award_no={new_nao[-1]['award_no']} entry_id={new_nao[-1]['entry_id']}")

    print("\n修正後の期待値:")
    print("  AKU: 143(2010H1)=赤染晶子 ... 174(2025H2)=鳥山まこと/畠山丑雄")
    print("  NAO: 113(1995H1)=赤瀬川隼 ... 142(2009H2)=佐々木譲 ... 174(2025H2)=嶋津輝")


if __name__ == "__main__":
    main()

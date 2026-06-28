"""
PLAM Version 1.4.1 — 回次監査スクリプト

CSVデータと公式サイト確認済みデータを照合して
award_no / award_year / award_term / title / author の整合性を検証する。

公式一次情報: 公益財団法人日本文学振興会
確認日: 2026-06-28

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/audit_award_numbers.py
  → reports/award_number_audit.md を生成
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime

PLAM_DIR    = Path("data/plam")
REPORTS_DIR = Path("reports")
AUDIT_PATH  = REPORTS_DIR / "award_number_audit.md"

# ── 公式確認済みデータ（サンプル検証ポイント） ──────────────────────────
# 各Phaseの先頭・末尾・代表作で照合する
# 形式: (award_id, award_no, award_year, award_term, title, author)
OFFICIAL_CHECKPOINTS = [
    # ── AKU Phase 1（2026-06-28 公式サイト確認済）──────────────
    ("AKU",   1, 1935, "H1", "蒼氓",                            "石川達三"),
    ("AKU",   2, 1935, "H2", None,                              None),  # no_award
    ("AKU",   3, 1936, "H1", "コシャマイン記",                    "鶴田知也"),
    ("AKU",   3, 1936, "H1", "城外",                            "小田嶽夫"),
    ("AKU",  29, 1953, "H1", "悪い仲間・陰気な愉しみ",            "安岡章太郎"),
    ("AKU",  32, 1954, "H2", "プールサイド小景",                  "庄野潤三"),
    ("AKU",  32, 1954, "H2", "アメリカン・スクール",              "小島信夫"),
    # ── AKU Phase 2（公式サイト確認済）──────────────────────────
    ("AKU",  33, 1955, "H1", "白い人",                           "遠藤周作"),
    ("AKU",  34, 1955, "H2", "太陽の季節",                       "石原慎太郎"),
    ("AKU",  72, 1974, "H2", "土の器",                           "阪田寛夫"),
    ("AKU",  72, 1974, "H2", "あの夕陽",                         "日野啓三"),
    # ── AKU Phase 3（公式サイト確認済）──────────────────────────
    ("AKU",  73, 1975, "H1", "祭りの場",                         "林京子"),
    ("AKU",  74, 1975, "H2", "岬",                              "中上健次"),
    ("AKU",  78, 1977, "H2", "螢川",                            "宮本輝"),
    ("AKU", 112, 1994, "H2", None,                              None),  # no_award
    # ── AKU Phase 4（公式サイト確認済）──────────────────────────
    ("AKU", 113, 1995, "H1", "この人の閾",                       "保坂和志"),
    ("AKU", 130, 2003, "H2", "蹴りたい背中",                     "綿矢りさ"),
    ("AKU", 142, 2009, "H2", None,                              None),  # no_award
    # ── AKU Phase 5（公式サイト確認済）──────────────────────────
    ("AKU", 143, 2010, "H1", "乙女の密告",                       "赤染晶子"),
    ("AKU", 145, 2011, "H1", None,                              None),  # no_award
    ("AKU", 153, 2015, "H1", "火花",                            "又吉直樹"),
    ("AKU", 169, 2023, "H1", "ハンチバック",                     "市川沙央"),
    ("AKU", 171, 2024, "H1", "サンショウウオの四十九日",          "朝比奈秋"),
    ("AKU", 171, 2024, "H1", "三蔵バリ山行",                     "松永K"),
    ("AKU", 172, 2024, "H2", "DTOPIA（デートピア）",             "安堂ホセ"),
    ("AKU", 173, 2025, "H1", None,                              None),  # no_award
    ("AKU", 174, 2025, "H2", "時の家",                          "鳥山まこと"),
    ("AKU", 174, 2025, "H2", "叫び",                            "畠山丑雄"),
    # ── NAO Phase 1（公式サイト確認済）──────────────────────────
    ("NAO",   1, 1935, "H1", "鶴八鶴次郎・風流深川唄 その他",    "川口松太郎"),
    ("NAO",   2, 1935, "H2", "吉野朝太平記",                     "鷲尾雨工"),
    ("NAO",   5, 1937, "H1", None,                              None),  # no_award
    ("NAO",  32, 1954, "H2", "高安犬物語",                       "戸川幸夫"),
    ("NAO",  32, 1954, "H2", "ボロ家の春秋",                     "梅崎春生"),
    # ── NAO Phase 2（公式サイト確認済）──────────────────────────
    ("NAO",  33, 1955, "H1", None,                              None),  # no_award
    ("NAO",  72, 1974, "H2", "アトラス伝説",                     "井出孫六"),
    # ── NAO Phase 3（公式サイト確認済）──────────────────────────
    ("NAO",  73, 1975, "H1", None,                              None),  # no_award
    ("NAO", 112, 1994, "H2", None,                              None),  # no_award
    # ── NAO Phase 4（公式サイト確認済）──────────────────────────
    ("NAO", 113, 1995, "H1", "白球残映",                         "赤瀬川隼"),
    ("NAO", 117, 1997, "H1", "鉄道員（ぽっぽや）",               "浅田次郎"),
    ("NAO", 134, 2005, "H2", "容疑者Ｘの献身",                   "東野圭吾"),
    ("NAO", 141, 2009, "H1", "鷺と雪",                          "北村薫"),
    ("NAO", 142, 2009, "H2", "廃墟に乞う",                       "佐々木譲"),
    ("NAO", 142, 2009, "H2", "ほかならぬ人へ",                   "白石一文"),
    # ── NAO Phase 5（公式サイト確認済）──────────────────────────
    # 143=2010H1 基点、算術検証: N = 143 + (year-2010)*2 + (H2=1, H1=0)
    ("NAO", 143, 2010, "H1", "小さいおうち",                     "中島京子"),
    ("NAO", 145, 2011, "H1", "下町ロケット",                     "池井戸潤"),   # 143+(2011-2010)*2+0=145
    ("NAO", 156, 2016, "H2", "蜜蜂と遠雷",                      "恩田陸"),     # 143+(2016-2010)*2+1=156
    ("NAO", 166, 2021, "H2", "黒牢城",                          "米澤穂信"),   # 143+(2021-2010)*2+1=166
    ("NAO", 173, 2025, "H1", None,                              None),  # no_award
    ("NAO", 174, 2025, "H2", "カフェーの帰り道",                 "嶋津輝"),
]


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


def normalize(s: str) -> str:
    import re
    return re.sub(r"[\s　・（）()「」『』]", "", (s or "")).lower()


def find_rows(rows: list[dict], award_id: str, award_no: int, award_term: str) -> list[dict]:
    return [r for r in rows
            if r.get("award_id") == award_id
            and str(r.get("award_no","")).strip() == str(award_no)
            and r.get("award_term","").strip() == award_term]


def check_point(rows: list[dict], award_id: str, award_no: int, award_year: int,
                award_term: str, exp_title: str | None, exp_author: str | None) -> dict:
    matching = find_rows(rows, award_id, award_no, award_term)

    # 期待がno_award（title=None）の場合
    if exp_title is None:
        no_awards = [r for r in matching if r.get("status") == "no_award"]
        if no_awards:
            yr = no_awards[0].get("award_year","")
            ok = str(yr) == str(award_year)
            return {"ok": ok, "msg": f"no_award year={yr}" if ok else f"year mismatch: got {yr}, expected {award_year}"}
        elif not matching:
            return {"ok": False, "msg": "行が存在しない"}
        else:
            return {"ok": False, "msg": f"no_award行がない (found: {[r['status'] for r in matching]})"}

    # 期待が受賞作の場合
    for r in matching:
        yr_ok  = str(r.get("award_year","")).strip() == str(award_year)
        tit_ok = normalize(r.get("title","")) == normalize(exp_title)
        aut_ok = exp_author is None or normalize(r.get("author","")) == normalize(exp_author)
        if tit_ok and aut_ok and yr_ok:
            return {"ok": True, "msg": f"{r.get('title')} / {r.get('author')}"}
        elif tit_ok:
            return {"ok": False, "msg": f"title OK but year={r.get('award_year')} author={r.get('author')} (expected year={award_year})"}

    if not matching:
        return {"ok": False, "msg": f"第{award_no}回{award_term} の行が存在しない"}
    return {"ok": False, "msg": f"title不一致: expected={exp_title}, got={[r.get('title') for r in matching]}"}


def main():
    REPORTS_DIR.mkdir(exist_ok=True)

    # 全CSVを結合
    all_rows: list[dict] = []
    for csv_path in PLAM_DIR.glob("*.csv"):
        if csv_path.name in {"awards_master.csv","works.csv","authors.csv",
                              "aliases.csv","award_history.csv"}:
            continue
        rows = read_csv(csv_path)
        if rows and "award_id" in rows[0]:
            all_rows.extend(rows)

    # フェーズ定義
    phases = {
        "AKU": [
            ("Phase 1",  1,  32),
            ("Phase 2", 33,  72),
            ("Phase 3", 73, 112),
            ("Phase 4",113, 142),
            ("Phase 5",143, 174),
        ],
        "NAO": [
            ("Phase 1",  1,  32),
            ("Phase 2", 33,  72),
            ("Phase 3", 73, 112),
            ("Phase 4",113, 142),
            ("Phase 5",143, 174),
        ],
    }

    # フェーズ別の実際の回次存在チェック
    phase_status: dict[str, dict[str, str]] = {}
    for aid, ph_list in phases.items():
        phase_status[aid] = {}
        rows_for_aid = [r for r in all_rows if r.get("award_id") == aid]
        award_nos = {int(r["award_no"]) for r in rows_for_aid if r.get("award_no","").isdigit()}
        for ph_name, start, end in ph_list:
            expected = set(range(start, end+1))
            missing  = expected - award_nos
            extra    = award_nos & set(range(start, end+1)) - expected  # always empty
            if missing:
                phase_status[aid][ph_name] = f"⚠️ 欠番あり: {sorted(missing)}"
            else:
                phase_status[aid][ph_name] = "✅ 全回次あり"

    # チェックポイント検証
    results = []
    ok_count = err_count = 0
    for (aid, no, yr, term, title, author) in OFFICIAL_CHECKPOINTS:
        r = check_point(all_rows, aid, no, yr, term, title, author)
        status = "✅ OK" if r["ok"] else "❌ NG"
        exp_str = title or "該当なし"
        if r["ok"]:
            ok_count += 1
        else:
            err_count += 1
        results.append((aid, no, yr, term, exp_str, status, r["msg"]))

    # レポート生成
    lines = [
        f"# PLAM 回次監査レポート (award_number_audit.md)",
        f"",
        f"生成日時: {datetime.now():%Y-%m-%d %H:%M}",
        f"情報源: 公益財団法人日本文学振興会（2026-06-28 確認）",
        f"",
        f"## サマリー",
        f"",
        f"- チェックポイント総数: {len(OFFICIAL_CHECKPOINTS)}",
        f"- ✅ OK: {ok_count}",
        f"- ❌ NG: {err_count}",
        f"",
        f"## フェーズ別 回次存在チェック",
        f"",
    ]

    for aid in ["AKU", "NAO"]:
        name = "芥川賞" if aid == "AKU" else "直木賞"
        lines.append(f"### {name} ({aid})")
        lines.append("")
        for ph_name, start, end in phases[aid]:
            st = phase_status[aid].get(ph_name, "不明")
            lines.append(f"- {ph_name} (第{start}〜{end}回): {st}")
        lines.append("")

    lines += [
        "## チェックポイント詳細",
        "",
        "| 賞 | 回 | 年 | 期 | 期待タイトル | 結果 | 備考 |",
        "|---|---|---|---|---|---|---|",
    ]

    for (aid, no, yr, term, exp_str, status, msg) in results:
        lines.append(f"| {aid} | {no} | {yr} | {term} | {exp_str} | {status} | {msg} |")

    lines += [
        "",
        "## 監査証跡",
        "",
        "- Phase1〜3: 公式サイト確認済み（2026-06-28）",
        "- Phase4: 公式サイト確認済み（2026-06-28）",
        "- Phase5: 公式サイト確認済み（2026-06-28）",
        "- 直木賞は芥川賞と同一回次（1935年第1回から同期）",
        "- 旧誤修正: Phase4 NAO を誤って+1→正しい値は変更なし（2026-06-28 修正）",
        "",
    ]

    AUDIT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{'='*50}")
    print(f"  回次監査完了")
    print(f"  ✅ OK: {ok_count} / ❌ NG: {err_count}")
    print(f"  レポート: {AUDIT_PATH}")
    print(f"{'='*50}")

    if err_count > 0:
        print("\n❌ エラー一覧:")
        for (aid, no, yr, term, exp_str, status, msg) in results:
            if status == "❌ NG":
                print(f"  {aid} 第{no}回{term} ({yr}): {exp_str} → {msg}")

    return err_count == 0


if __name__ == "__main__":
    import sys
    ok = main()
    sys.exit(0 if ok else 1)

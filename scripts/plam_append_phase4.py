"""
PLAM Phase 4 データ追加スクリプト（芥川賞・直木賞 第113〜142回 1995-2009年）
公式情報源: 公益財団法人日本文学振興会
checked: 2026-06-28

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_append_phase4.py
"""
import csv
from pathlib import Path

PLAM_DIR = Path("data/plam")

AKU_PHASE4 = [
    # fmt: entry_id, award_year, award_no, award_term, title, author, status
    ("AKU-113-H1-01", 1995, 113, "H1", "この人の閾",            "保坂和志",    "awarded"),
    ("AKU-114-H2-01", 1995, 114, "H2", "豚の報い",              "又吉栄喜",    "awarded"),
    ("AKU-115-H1-01", 1996, 115, "H1", "蛇を踏む",              "川上弘美",    "awarded"),
    ("AKU-116-H2-01", 1996, 116, "H2", "海峡の光",              "辻仁成",      "co_winner"),
    ("AKU-116-H2-02", 1996, 116, "H2", "家族シネマ",            "柳美里",      "co_winner"),
    ("AKU-117-H1-01", 1997, 117, "H1", "水滴",                  "目取真俊",    "awarded"),
    ("AKU-118-H2-00", 1997, 118, "H2", "",                      "",            "no_award"),
    ("AKU-119-H1-01", 1998, 119, "H1", "ブエノスアイレス午前零時", "藤沢周",   "co_winner"),
    ("AKU-119-H1-02", 1998, 119, "H1", "ゲルマニウムの夜",      "花村萬月",    "co_winner"),
    ("AKU-120-H2-01", 1998, 120, "H2", "日蝕",                  "平野啓一郎",  "awarded"),
    ("AKU-121-H1-00", 1999, 121, "H1", "",                      "",            "no_award"),
    ("AKU-122-H2-01", 1999, 122, "H2", "蔭の棲みか",            "玄月",        "co_winner"),
    ("AKU-122-H2-02", 1999, 122, "H2", "夏の約束",              "藤野千夜",    "co_winner"),
    ("AKU-123-H1-01", 2000, 123, "H1", "花腐し",                "松浦寿輝",    "co_winner"),
    ("AKU-123-H1-02", 2000, 123, "H1", "きれぎれ",              "町田康",      "co_winner"),
    ("AKU-124-H2-01", 2000, 124, "H2", "熊の敷石",              "堀江敏幸",    "co_winner"),
    ("AKU-124-H2-02", 2000, 124, "H2", "聖水",                  "青来有一",    "co_winner"),
    ("AKU-125-H1-01", 2001, 125, "H1", "中陰の花",              "玄侑宗久",    "awarded"),
    ("AKU-126-H2-01", 2001, 126, "H2", "猛スピードで母は",      "長嶋有",      "awarded"),
    ("AKU-127-H1-01", 2002, 127, "H1", "パーク・ライフ",        "吉田修一",    "awarded"),
    ("AKU-128-H2-01", 2002, 128, "H2", "しょっぱいドライブ",    "大道珠貴",    "awarded"),
    ("AKU-129-H1-01", 2003, 129, "H1", "ハリガネムシ",          "吉村萬壱",    "awarded"),
    ("AKU-130-H2-01", 2003, 130, "H2", "蹴りたい背中",          "綿矢りさ",    "co_winner"),
    ("AKU-130-H2-02", 2003, 130, "H2", "蛇にピアス",            "金原ひとみ",  "co_winner"),
    ("AKU-131-H1-01", 2004, 131, "H1", "介護入門",              "モブ・ノリオ","awarded"),
    ("AKU-132-H2-01", 2004, 132, "H2", "グランド・フィナーレ",  "阿部和重",    "awarded"),
    ("AKU-133-H1-01", 2005, 133, "H1", "土の中の子供",          "中村文則",    "awarded"),
    ("AKU-134-H2-01", 2005, 134, "H2", "沖で待つ",              "絲山秋子",    "awarded"),
    ("AKU-135-H1-01", 2006, 135, "H1", "八月の路上に捨てる",    "伊藤たかみ",  "awarded"),
    ("AKU-136-H2-01", 2006, 136, "H2", "ひとり日和",            "青山七恵",    "awarded"),
    ("AKU-137-H1-01", 2007, 137, "H1", "アサッテの人",          "諏訪哲史",    "awarded"),
    ("AKU-138-H2-01", 2007, 138, "H2", "乳と卵",                "川上未映子",  "awarded"),
    ("AKU-139-H1-01", 2008, 139, "H1", "時が滲む朝",            "楊逸",        "awarded"),
    ("AKU-140-H2-01", 2008, 140, "H2", "ポトスライムの舟",      "津村記久子",  "awarded"),
    ("AKU-141-H1-01", 2009, 141, "H1", "終の住処",              "磯崎憲一郎",  "awarded"),
    ("AKU-142-H2-00", 2009, 142, "H2", "",                      "",            "no_award"),
]

NAO_PHASE4 = [
    ("NAO-113-H1-01", 1995, 113, "H1", "白球残映",                       "赤瀬川隼",   "awarded"),
    ("NAO-114-H2-01", 1995, 114, "H2", "テロリストのパラソル",            "藤原伊織",   "co_winner"),
    ("NAO-114-H2-02", 1995, 114, "H2", "恋",                             "小池真理子", "co_winner"),
    ("NAO-115-H1-01", 1996, 115, "H1", "凍える牙",                       "乃南アサ",   "awarded"),
    ("NAO-116-H2-01", 1996, 116, "H2", "山妣",                           "坂東眞砂子", "awarded"),
    ("NAO-117-H1-01", 1997, 117, "H1", "鉄道員（ぽっぽや）",             "浅田次郎",   "co_winner"),
    ("NAO-117-H1-02", 1997, 117, "H1", "女たちのジハード",                "篠田節子",   "co_winner"),
    ("NAO-118-H2-00", 1997, 118, "H2", "",                               "",           "no_award"),
    ("NAO-119-H1-01", 1998, 119, "H1", "赤目四十八瀧心中未遂",           "車谷長吉",   "awarded"),
    ("NAO-120-H2-01", 1998, 120, "H2", "理由",                           "宮部みゆき", "awarded"),
    ("NAO-121-H1-01", 1999, 121, "H1", "柔らかな頬",                     "桐野夏生",   "co_winner"),
    ("NAO-121-H1-02", 1999, 121, "H1", "王妃の離婚",                     "佐藤賢一",   "co_winner"),
    ("NAO-122-H2-01", 1999, 122, "H2", "長崎ぶらぶら節",                 "なかにし礼", "awarded"),
    ("NAO-123-H1-01", 2000, 123, "H1", "虹の谷の五月",                   "船戸与一",   "co_winner"),
    ("NAO-123-H1-02", 2000, 123, "H1", "GO",                             "金城一紀",   "co_winner"),
    ("NAO-124-H2-01", 2000, 124, "H2", "プラナリア",                     "山本文緒",   "co_winner"),
    ("NAO-124-H2-02", 2000, 124, "H2", "ビタミンF",                      "重松清",     "co_winner"),
    ("NAO-125-H1-01", 2001, 125, "H1", "愛の領分",                       "藤田宜永",   "awarded"),
    ("NAO-126-H2-01", 2001, 126, "H2", "肩ごしの恋人",                   "唯川恵",     "co_winner"),
    ("NAO-126-H2-02", 2001, 126, "H2", "あかね空",                       "山本一力",   "co_winner"),
    ("NAO-127-H1-01", 2002, 127, "H1", "生きる",                         "乙川優三郎", "awarded"),
    ("NAO-128-H2-00", 2002, 128, "H2", "",                               "",           "no_award"),
    ("NAO-129-H1-01", 2003, 129, "H1", "星々の舟",                       "村山由佳",   "co_winner"),
    ("NAO-129-H1-02", 2003, 129, "H1", "4TEEN フォーティーン",           "石田衣良",   "co_winner"),
    ("NAO-130-H2-01", 2003, 130, "H2", "後巷説百物語",                   "京極夏彦",   "co_winner"),
    ("NAO-130-H2-02", 2003, 130, "H2", "号泣する準備はできていた",        "江國香織",   "co_winner"),
    ("NAO-131-H1-01", 2004, 131, "H1", "邂逅の森",                       "熊谷達也",   "co_winner"),
    ("NAO-131-H1-02", 2004, 131, "H1", "空中ブランコ",                   "奥田英朗",   "co_winner"),
    ("NAO-132-H2-01", 2004, 132, "H2", "対岸の彼女",                     "角田光代",   "awarded"),
    ("NAO-133-H1-01", 2005, 133, "H1", "花まんま",                       "朱川湊人",   "awarded"),
    ("NAO-134-H2-01", 2005, 134, "H2", "容疑者Ｘの献身",                 "東野圭吾",   "awarded"),
    ("NAO-135-H1-01", 2006, 135, "H1", "風に舞いあがるビニールシート",    "森絵都",     "co_winner"),
    ("NAO-135-H1-02", 2006, 135, "H1", "まほろ駅前多田便利軒",           "三浦しをん", "co_winner"),
    ("NAO-136-H2-00", 2006, 136, "H2", "",                               "",           "no_award"),
    ("NAO-137-H1-01", 2007, 137, "H1", "吉原手引草",                     "松井今朝子", "awarded"),
    ("NAO-138-H2-01", 2007, 138, "H2", "私の男",                         "桜庭一樹",   "awarded"),
    ("NAO-139-H1-01", 2008, 139, "H1", "切羽へ",                         "井上荒野",   "awarded"),
    ("NAO-140-H2-01", 2008, 140, "H2", "利休にたずねよ",                 "山本兼一",   "co_winner"),
    ("NAO-140-H2-02", 2008, 140, "H2", "悼む人",                         "天童荒太",   "co_winner"),
    ("NAO-141-H1-01", 2009, 141, "H1", "鷺と雪",                         "北村薫",     "awarded"),
    ("NAO-142-H2-01", 2009, 142, "H2", "廃墟に乞う",                     "佐々木譲",   "co_winner"),
    ("NAO-142-H2-02", 2009, 142, "H2", "ほかならぬ人へ",                 "白石一文",   "co_winner"),
]


def append_rows(csv_path: Path, award_id: str, award_name: str, rows_data: list) -> None:
    fieldnames = ["entry_id","work_id","award_id","award_name","award_year",
                  "award_no","award_term","title","author","isbn13","isbn_status","status","remarks"]

    new_rows = []
    for entry_id, award_year, award_no, award_term, title, author, status in rows_data:
        new_rows.append({
            "entry_id":   entry_id,
            "work_id":    "",
            "award_id":   award_id,
            "award_name": award_name,
            "award_year": award_year,
            "award_no":   award_no,
            "award_term": award_term,
            "title":      title,
            "author":     author,
            "isbn13":     "",
            "isbn_status":"missing",
            "status":     status,
            "remarks":    "",
        })

    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(new_rows)

    print(f"✅ {csv_path.name} に {len(new_rows)} 行追加")


def main():
    aku_path = PLAM_DIR / "akutagawa_prize.csv"
    nao_path = PLAM_DIR / "naoki_prize.csv"

    append_rows(aku_path, "AKU", "芥川賞", AKU_PHASE4)
    append_rows(nao_path, "NAO", "直木賞", NAO_PHASE4)

    print(f"\n芥川賞 Phase4 追加: {len(AKU_PHASE4)} 行 (第113〜142回)")
    print(f"直木賞 Phase4 追加: {len(NAO_PHASE4)} 行 (第113〜142回)")
    print("\n次のステップ:")
    print("  python3 scripts/plam_assign_work_ids.py")
    print("  python3 scripts/plam_build_v13.py")
    print("  python3 scripts/plam_validate.py data/plam/akutagawa_prize.csv data/plam/naoki_prize.csv")


if __name__ == "__main__":
    main()

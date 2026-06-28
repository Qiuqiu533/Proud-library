"""
PLAM Phase 5 データ追加スクリプト（芥川賞・直木賞 2010-2025年）
公式情報源: 公益財団法人日本文学振興会
checked: 2026-06-28

芥川賞: 第143〜172回
直木賞: 第144〜175回（直木賞は常に芥川賞より1回先行）

使い方:
  cd /tmp/Proud-library-fresh
  python3 scripts/plam_append_phase5.py
"""
import csv
from pathlib import Path

PLAM_DIR = Path("data/plam")

# 芥川賞 Phase 5: 第143〜172回 (2010〜2024年)
AKU_PHASE5 = [
    # entry_id, award_year, award_no, award_term, title, author, status
    ("AKU-143-H1-01", 2010, 143, "H1", "乙女の密告",                       "赤染晶子",   "awarded"),
    ("AKU-144-H2-01", 2010, 144, "H2", "苦役列車",                         "西村賢太",   "co_winner"),
    ("AKU-144-H2-02", 2010, 144, "H2", "きことわ",                         "朝吹真理子", "co_winner"),
    ("AKU-145-H1-00", 2011, 145, "H1", "",                                 "",           "no_award"),
    ("AKU-146-H2-01", 2011, 146, "H2", "共喰い",                           "田中慎弥",   "co_winner"),
    ("AKU-146-H2-02", 2011, 146, "H2", "道化師の蝶",                       "円城塔",     "co_winner"),
    ("AKU-147-H1-01", 2012, 147, "H1", "冥土めぐり",                       "鹿島田真希", "awarded"),
    ("AKU-148-H2-01", 2012, 148, "H2", "ａｂさんご",                       "黒田夏子",   "awarded"),
    ("AKU-149-H1-01", 2013, 149, "H1", "爪と目",                           "藤野可織",   "awarded"),
    ("AKU-150-H2-01", 2013, 150, "H2", "穴",                               "小山田浩子", "awarded"),
    ("AKU-151-H1-01", 2014, 151, "H1", "春の庭",                           "柴崎友香",   "awarded"),
    ("AKU-152-H2-01", 2014, 152, "H2", "九年前の祈り",                     "小野正嗣",   "awarded"),
    ("AKU-153-H1-01", 2015, 153, "H1", "火花",                             "又吉直樹",   "co_winner"),
    ("AKU-153-H1-02", 2015, 153, "H1", "スクラップ・アンド・ビルド",        "羽田圭介",   "co_winner"),
    ("AKU-154-H2-01", 2015, 154, "H2", "異類婚姻譚",                       "本谷有希子", "co_winner"),
    ("AKU-154-H2-02", 2015, 154, "H2", "死んでいない者",                   "滝口悠生",   "co_winner"),
    ("AKU-155-H1-01", 2016, 155, "H1", "コンビニ人間",                     "村田沙耶香", "awarded"),
    ("AKU-156-H2-01", 2016, 156, "H2", "しんせかい",                       "山下澄人",   "awarded"),
    ("AKU-157-H1-01", 2017, 157, "H1", "影裏",                             "沼田真佑",   "awarded"),
    ("AKU-158-H2-01", 2017, 158, "H2", "百年泥",                           "石井遊佳",   "co_winner"),
    ("AKU-158-H2-02", 2017, 158, "H2", "おらおらでひとりいぐも",           "若竹千佐子", "co_winner"),
    ("AKU-159-H1-01", 2018, 159, "H1", "送り火",                           "高橋弘希",   "awarded"),
    ("AKU-160-H2-01", 2018, 160, "H2", "ニムロッド",                       "上田岳弘",   "co_winner"),
    ("AKU-160-H2-02", 2018, 160, "H2", "1R1分34秒",                        "町屋良平",   "co_winner"),
    ("AKU-161-H1-01", 2019, 161, "H1", "むらさきのスカートの女",           "今村夏子",   "awarded"),
    ("AKU-162-H2-01", 2019, 162, "H2", "背高泡立草",                       "古川真人",   "awarded"),
    ("AKU-163-H1-01", 2020, 163, "H1", "首里の馬",                         "高山羽根子", "co_winner"),
    ("AKU-163-H1-02", 2020, 163, "H1", "破局",                             "遠野遥",     "co_winner"),
    ("AKU-164-H2-01", 2020, 164, "H2", "推し、燃ゆ",                       "宇佐見りん", "awarded"),
    ("AKU-165-H1-01", 2021, 165, "H1", "貝に続く場所にて",                 "石沢麻依",   "co_winner"),
    ("AKU-165-H1-02", 2021, 165, "H1", "彼岸花が咲く島",                   "李琴峰",     "co_winner"),
    ("AKU-166-H2-01", 2021, 166, "H2", "ブラックボックス",                 "砂川文次",   "awarded"),
    ("AKU-167-H1-01", 2022, 167, "H1", "おいしいごはんが食べられますように","高瀬隼子",   "awarded"),
    ("AKU-168-H2-01", 2022, 168, "H2", "この世の喜びよ",                   "井戸川射子", "co_winner"),
    ("AKU-168-H2-02", 2022, 168, "H2", "荒地の家族",                       "佐藤厚志",   "co_winner"),
    ("AKU-169-H1-01", 2023, 169, "H1", "ハンチバック",                     "市川沙央",   "awarded"),
    ("AKU-170-H2-01", 2023, 170, "H2", "東京都同情塔",                     "九段理江",   "awarded"),
    ("AKU-171-H1-01", 2024, 171, "H1", "サンショウウオの四十九日",         "朝比奈秋",   "co_winner"),
    ("AKU-171-H1-02", 2024, 171, "H1", "三蔵バリ山行",                     "松永K三郎",  "co_winner"),
    ("AKU-172-H2-01", 2024, 172, "H2", "DTOPIA（デートピア）",             "安堂ホセ",   "co_winner"),
    ("AKU-172-H2-02", 2024, 172, "H2", "ゲーテはすべてを言った",           "鈴木結生",   "co_winner"),
]

# 直木賞 Phase 5: 第144〜175回 (2010〜2025年)
NAO_PHASE5 = [
    ("NAO-144-H1-01", 2010, 144, "H1", "小さいおうち",                         "中島京子",   "awarded"),
    ("NAO-145-H2-01", 2010, 145, "H2", "月と蟹",                               "道尾秀介",   "co_winner"),
    ("NAO-145-H2-02", 2010, 145, "H2", "漂砂のうたう",                         "木内昇",     "co_winner"),
    ("NAO-146-H1-01", 2011, 146, "H1", "下町ロケット",                         "池井戸潤",   "awarded"),
    ("NAO-147-H2-01", 2011, 147, "H2", "蜩ノ記",                               "葉室麟",     "awarded"),
    ("NAO-148-H1-01", 2012, 148, "H1", "鍵のない夢を見る",                     "辻村深月",   "awarded"),
    ("NAO-149-H2-01", 2012, 149, "H2", "等伯",                                 "安部龍太郎", "co_winner"),
    ("NAO-149-H2-02", 2012, 149, "H2", "何者",                                 "朝井リョウ", "co_winner"),
    ("NAO-150-H1-01", 2013, 150, "H1", "ホテルローヤル",                       "桜木紫乃",   "awarded"),
    ("NAO-151-H2-01", 2013, 151, "H2", "昭和の犬",                             "姫野カオルコ","co_winner"),
    ("NAO-151-H2-02", 2013, 151, "H2", "恋歌",                                 "朝井まかて", "co_winner"),
    ("NAO-152-H1-01", 2014, 152, "H1", "破門",                                 "黒川博行",   "awarded"),
    ("NAO-153-H2-01", 2014, 153, "H2", "サラバ！",                             "西加奈子",   "awarded"),
    ("NAO-154-H1-01", 2015, 154, "H1", "流",                                   "東山彰良",   "awarded"),
    ("NAO-155-H2-01", 2015, 155, "H2", "つまをめとらば",                       "青山文平",   "awarded"),
    ("NAO-156-H1-01", 2016, 156, "H1", "海の見える理髪店",                     "荻原浩",     "awarded"),
    ("NAO-157-H2-01", 2016, 157, "H2", "蜜蜂と遠雷",                           "恩田陸",     "awarded"),
    ("NAO-158-H1-01", 2017, 158, "H1", "月の満ち欠け",                         "佐藤正午",   "awarded"),
    ("NAO-159-H2-01", 2017, 159, "H2", "銀河鉄道の父",                         "門井慶喜",   "awarded"),
    ("NAO-160-H1-01", 2018, 160, "H1", "ファーストラヴ",                       "島本理生",   "awarded"),
    ("NAO-161-H2-01", 2018, 161, "H2", "宝島",                                 "真藤順丈",   "awarded"),
    ("NAO-162-H1-01", 2019, 162, "H1", "渦 妹背山婦女庭訓 魂結び",            "大島真寿美", "awarded"),
    ("NAO-163-H2-01", 2019, 163, "H2", "熱源",                                 "川越宗一",   "awarded"),
    ("NAO-164-H1-01", 2020, 164, "H1", "少年と犬",                             "馳星周",     "awarded"),
    ("NAO-165-H2-01", 2020, 165, "H2", "心淋し川",                             "西條奈加",   "awarded"),
    ("NAO-166-H1-01", 2021, 166, "H1", "テスカトリポカ",                       "佐藤究",     "co_winner"),
    ("NAO-166-H1-02", 2021, 166, "H1", "星落ちて、なお",                       "澤田瞳子",   "co_winner"),
    ("NAO-167-H2-01", 2021, 167, "H2", "塞王の楯",                             "今村翔吾",   "co_winner"),
    ("NAO-167-H2-02", 2021, 167, "H2", "黒牢城",                               "米澤穂信",   "co_winner"),
    ("NAO-168-H1-01", 2022, 168, "H1", "夜に星を放つ",                         "窪美澄",     "awarded"),
    ("NAO-169-H2-01", 2022, 169, "H2", "地図と拳",                             "小川哲",     "co_winner"),
    ("NAO-169-H2-02", 2022, 169, "H2", "しろがねの葉",                         "千早茜",     "co_winner"),
    ("NAO-170-H1-01", 2023, 170, "H1", "極楽征夷大将軍",                       "垣根涼介",   "co_winner"),
    ("NAO-170-H1-02", 2023, 170, "H1", "木挽町のあだ討ち",                     "永井紗耶子", "co_winner"),
    ("NAO-171-H2-01", 2023, 171, "H2", "ともぐい",                             "河﨑秋子",   "co_winner"),
    ("NAO-171-H2-02", 2023, 171, "H2", "八月の御所グラウンド",                 "万城目学",   "co_winner"),
    ("NAO-172-H1-01", 2024, 172, "H1", "ツミデミック",                         "一穂ミチ",   "awarded"),
    ("NAO-173-H2-01", 2024, 173, "H2", "藍を継ぐ海",                           "伊与原新",   "awarded"),
    ("NAO-174-H1-00", 2025, 174, "H1", "",                                     "",           "no_award"),
    ("NAO-175-H2-01", 2025, 175, "H2", "カフェーの帰り道",                     "嶋津輝",     "awarded"),
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

    append_rows(aku_path, "AKU", "芥川賞", AKU_PHASE5)
    append_rows(nao_path, "NAO", "直木賞", NAO_PHASE5)

    print(f"\n芥川賞 Phase5 追加: {len(AKU_PHASE5)} 行 (第143〜172回 2010-2024年)")
    print(f"直木賞 Phase5 追加: {len(NAO_PHASE5)} 行 (第144〜175回 2010-2025年)")


if __name__ == "__main__":
    main()

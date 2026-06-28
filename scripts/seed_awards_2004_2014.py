"""
直木賞・芥川賞 2004〜2014年（第131〜152回）の正確なデータをDBに登録するスクリプト
データソース: 公益財団法人日本文学振興会 公式サイト
  https://bungakushinko.or.jp/award/naoki/list.html
  https://bungakushinko.or.jp/award/akutagawa/list.html

手順:
  cd /tmp/Proud-library-fresh
  set -a && source .env.review && set +a
  python3 scripts/seed_awards_2004_2014.py [--dry-run]
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DATABASE_URL = os.environ.get("DATABASE_URL", "")

AWARDS_DATA = [
    # (award, award_no, award_year, title, author)
    # ─── 直木賞 ───
    ("直木賞", 131, 2004, "邂逅の森",              "熊谷達也"),
    ("直木賞", 131, 2004, "空中ブランコ",           "奥田英朗"),
    ("直木賞", 132, 2004, "対岸の彼女",             "角田光代"),
    ("直木賞", 133, 2005, "花まんま",               "朱川湊人"),
    ("直木賞", 134, 2005, "容疑者Ｘの献身",         "東野圭吾"),
    ("直木賞", 135, 2006, "風に舞いあがるビニールシート", "森絵都"),
    ("直木賞", 135, 2006, "まほろ駅前多田便利軒",   "三浦しをん"),
    ("直木賞", 137, 2007, "吉原手引草",             "松井今朝子"),
    ("直木賞", 138, 2007, "私の男",                 "桜庭一樹"),
    ("直木賞", 139, 2008, "切羽へ",                 "井上荒野"),
    ("直木賞", 140, 2008, "利休にたずねよ",         "山本兼一"),
    ("直木賞", 140, 2008, "悼む人",                 "天童荒太"),
    ("直木賞", 141, 2009, "鷺と雪",                 "北村薫"),
    ("直木賞", 142, 2009, "廃墟に乞う",             "佐々木譲"),
    ("直木賞", 142, 2009, "ほかならぬ人へ",         "白石一文"),
    ("直木賞", 143, 2010, "小さいおうち",           "中島京子"),
    ("直木賞", 144, 2010, "月と蟹",                 "道尾秀介"),
    ("直木賞", 144, 2010, "漂砂のうたう",           "木内昇"),
    ("直木賞", 145, 2011, "下町ロケット",           "池井戸潤"),
    ("直木賞", 146, 2011, "蜩ノ記",                 "葉室麟"),
    ("直木賞", 147, 2012, "鍵のない夢を見る",       "辻村深月"),
    ("直木賞", 148, 2012, "等伯",                   "安部龍太郎"),
    ("直木賞", 148, 2012, "何者",                   "朝井リョウ"),
    ("直木賞", 149, 2013, "ホテルローヤル",         "桜木紫乃"),
    ("直木賞", 150, 2013, "昭和の犬",               "姫野カオルコ"),
    ("直木賞", 150, 2013, "恋歌",                   "朝井まかて"),
    ("直木賞", 151, 2014, "破門",                   "黒川博行"),
    ("直木賞", 152, 2014, "サラバ！",               "西加奈子"),
    # ─── 芥川賞 ───
    ("芥川賞", 131, 2004, "介護入門",               "モブ・ノリオ"),
    ("芥川賞", 132, 2004, "グランド・フィナーレ",   "阿部和重"),
    ("芥川賞", 133, 2005, "土の中の子供",           "中村文則"),
    ("芥川賞", 134, 2005, "沖で待つ",               "絲山秋子"),
    ("芥川賞", 135, 2006, "八月の路上に捨てる",     "伊藤たかみ"),
    ("芥川賞", 136, 2006, "ひとり日和",             "青山七恵"),
    ("芥川賞", 137, 2007, "アサッテの人",           "諏訪哲史"),
    ("芥川賞", 138, 2007, "乳と卵",                 "川上未映子"),
    ("芥川賞", 139, 2008, "時が滲む朝",             "楊逸"),
    ("芥川賞", 140, 2008, "ポトスライムの舟",       "津村記久子"),
    ("芥川賞", 141, 2009, "終の住処",               "磯崎憲一郎"),
    ("芥川賞", 143, 2010, "乙女の密告",             "赤染晶子"),
    ("芥川賞", 144, 2010, "苦役列車",               "西村賢太"),
    ("芥川賞", 144, 2010, "きことわ",               "朝吹真理子"),
    ("芥川賞", 146, 2011, "共喰い",                 "田中慎弥"),
    ("芥川賞", 146, 2011, "道化師の蝶",             "円城塔"),
    ("芥川賞", 147, 2012, "冥土めぐり",             "鹿島田真希"),
    ("芥川賞", 148, 2012, "ａｂさんご",             "黒田夏子"),
    ("芥川賞", 149, 2013, "爪と目",                 "藤野可織"),
    ("芥川賞", 150, 2013, "穴",                     "小山田浩子"),
    ("芥川賞", 151, 2014, "春の庭",                 "柴崎友香"),
    ("芥川賞", 152, 2014, "九年前の祈り",           "小野正嗣"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if DATABASE_URL:
        import psycopg2
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        con = psycopg2.connect(url)
        PH = "%s"
    else:
        import sqlite3
        con = sqlite3.connect(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.db"))
        PH = "?"

    cur = con.cursor()

    # 既存の2004-2014年データを確認
    cur.execute(
        f"SELECT count(*) FROM award_books WHERE award IN ('直木賞','芥川賞') AND award_year BETWEEN 2004 AND 2014"
    )
    existing_count = cur.fetchone()[0]
    print(f"既存データ: {existing_count} 件（削除予定）")

    if not args.dry_run:
        cur.execute(
            f"DELETE FROM award_books WHERE award IN ('直木賞','芥川賞') AND award_year BETWEEN 2004 AND 2014"
        )
        print(f"  → {cur.rowcount} 件削除")

    print(f"\n新規登録: {len(AWARDS_DATA)} 件")
    for award, award_no, award_year, title, author in AWARDS_DATA:
        print(f"  {award} 第{award_no}回 {award_year}年: {title}（{author}）")
        if not args.dry_run:
            cur.execute(
                f"INSERT INTO award_books (award, award_no, award_year, title, author, status) VALUES ({PH},{PH},{PH},{PH},{PH},'active')",
                (award, award_no, award_year, title, author)
            )

    if not args.dry_run:
        con.commit()
        print(f"\n✅ 登録完了")
    else:
        print(f"\n[dry-run] 実際には変更しませんでした")

    con.close()


if __name__ == "__main__":
    main()

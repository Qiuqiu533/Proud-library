"""
受賞マスターシードデータの整合性テスト。
誤った受賞データの混入を自動検出する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from seeds import _AWARDS_SEED

# ── 正しいことが確定している受賞データ ───────────────────────────────────────
MUST_EXIST = [
    ("直木賞", 2024, "ともぐい",           "河崎秋子"),
    ("直木賞", 2024, "八月の御所グラウンド", "万城目学"),
    ("直木賞", 2023, "木挽町のあだ討ち",    "永井紗耶子"),
    ("直木賞", 2023, "極楽征夷大将軍",      "垣根涼介"),
    ("直木賞", 2023, "しろがねの葉",        "千早茜"),
    ("直木賞", 2022, "黒牢城",             "米澤穂信"),
    ("直木賞", 2022, "夜に星を放つ",        "窪美澄"),
    ("直木賞", 2021, "テスカトリポカ",      "佐藤究"),
    ("直木賞", 2021, "心淋し川",           "西條奈加"),
    ("直木賞", 2021, "星落ちて、なお",      "澤田瞳子"),
    ("直木賞", 2020, "少年と犬",           "馳星周"),
    ("直木賞", 2020, "熱源",              "川越宗一"),
    ("直木賞", 2019, "渦 妹背山婦女庭訓 魂結び", "大島真寿美"),
    ("直木賞", 2018, "ファーストラヴ",      "島本理生"),
    ("直木賞", 2018, "銀河鉄道の父",       "門井慶喜"),
    ("直木賞", 2017, "蜜蜂と遠雷",         "恩田陸"),
    ("直木賞", 1996, "テロリストのパラソル", "藤原伊織"),
    ("江戸川乱歩賞", 1995, "テロリストのパラソル", "藤原伊織"),
    ("江戸川乱歩賞", 1998, "果つる底なき",  "池井戸潤"),
    ("江戸川乱歩賞", 1985, "放課後",        "東野圭吾"),
    ("山本周五郎賞", 2024, "スピノザの診察室", "夏川草介"),
    ("山本周五郎賞", 2023, "汝、星のごとく", "凪良ゆう"),
    ("本格ミステリ大賞", 2022, "黒牢城",    "米澤穂信"),
]

# ── 過去に誤って混入した（はずの）データが除去されているか確認 ────────────────
MUST_NOT_EXIST = [
    ("直木賞", 2020, "少女は卒業しない",             "朝井リョウ"),  # 誤り: 朝井の直木賞は「何者」
    ("直木賞", 2021, "また会う日まで",               "池井戸潤"),   # 誤り: 池井戸潤は直木賞未受賞
    ("直木賞", 2018, "サクリファイス",               "近藤史恵"),   # 誤り: 直木賞未受賞
    ("直木賞", 2018, "大きな鳥にさらわれないよう",   "川上弘美"),   # 誤り: 芥川賞受賞者
    ("直木賞", 2019, "べらぼうくん",                "木下昌輝"),   # 誤り: 候補止まり
    ("直木賞", 2022, "テスカトリポカ",              "佐藤究"),     # 年誤り: 正しくは2021年
    ("直木賞", 2022, "心淋し川",                   "西條奈加"),   # 年誤り: 正しくは2021年
]


def _seed_set():
    """(award, year, title, author) のセットを返す。"""
    return {(a, y, t, au) for (a, y, _, __, t, au) in _AWARDS_SEED}


def test_must_exist():
    s = _seed_set()
    missing = [(award, year, title, author) for (award, year, title, author) in MUST_EXIST
               if (award, year, title, author) not in s]
    assert not missing, f"シードデータに必須エントリが欠落しています: {missing}"


def test_must_not_exist():
    s = _seed_set()
    found = [(award, year, title, author) for (award, year, title, author) in MUST_NOT_EXIST
             if (award, year, title, author) in s]
    assert not found, f"誤ったエントリがシードデータに混入しています: {found}"


def test_no_duplicate_entries():
    entries = [(a, y, t, au) for (a, y, _, __, t, au) in _AWARDS_SEED]
    seen = set()
    dups = []
    for e in entries:
        if e in seen:
            dups.append(e)
        seen.add(e)
    assert not dups, f"シードデータに重複エントリがあります: {dups}"


def test_years_are_reasonable():
    """受賞年が妥当な範囲内か確認（1950〜2030）。"""
    bad = [(a, y, t) for (a, y, _, __, t, au) in _AWARDS_SEED if y is not None and not (1950 <= y <= 2030)]
    assert not bad, f"受賞年が範囲外です: {bad}"

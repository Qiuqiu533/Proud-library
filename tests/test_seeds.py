"""
受賞マスターシードデータの整合性テスト。
誤った受賞データの混入を自動検出する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from seeds import _AWARDS_SEED, _AWARD_BOOKS_SEED
from migrations import AWARD_BOOKS_SEEDS_MIN_ROUND

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


# ── award_books（受賞作DBタブ用）シードデータのテスト ─────────────────────────

NOMA_MUST_EXIST = [
    (78, 2025, "世界99（上・下）", "村田沙耶香"),
    (77, 2024, "列", "中村文則"),
    (76, 2023, "恋ははかない、あるいは、プールの底のステーキ", "川上弘美"),
    (63, 2010, "故郷のわが家", "村田喜代子"),
]


def test_award_books_tuple_length_consistent():
    """_AWARD_BOOKS_SEED の全タプルが6要素（部門なし）または7要素（award_category付き、
    読売文学賞等の部門制の賞）のいずれかで統一されているか確認。"""
    bad = [t for t in _AWARD_BOOKS_SEED if len(t) not in (6, 7)]
    assert not bad, f"タプル長が6・7以外のエントリがあります: {bad}"


def test_award_books_noma_count():
    """野間文芸賞が第63〜78回（2010〜2025年）の16件登録されているか確認。"""
    noma = [t for t in _AWARD_BOOKS_SEED if t[0] == "野間文芸賞"]
    assert len(noma) == 16, f"野間文芸賞の件数が想定と異なります: {len(noma)}件"


def test_award_books_noma_must_exist():
    """野間文芸賞の主要エントリ（講談社公式・Wikipedia照合済み）が存在するか確認。"""
    noma_set = {(t[1], t[2], t[3], t[4]) for t in _AWARD_BOOKS_SEED if t[0] == "野間文芸賞"}
    missing = [e for e in NOMA_MUST_EXIST if e not in noma_set]
    assert not missing, f"野間文芸賞の必須エントリが欠落しています: {missing}"


def test_award_books_yomiuri_novel_rounds():
    """読売文学賞・小説賞の受賞枠（回次単位）とレコード数（行単位、共同受賞は複数行）を
    それぞれ検証する。第5・10・13回は受賞作なしのため欠番が正しい状態。"""
    rows = [t for t in _AWARD_BOOKS_SEED if t[0] == "読売文学賞" and t[6] == "小説賞"]
    rounds = {t[1] for t in rows}
    expected_rounds = {
        1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 24, 25, 26, 27, 28, 29, 30,
        31, 33, 34, 36, 37, 38, 39, 40,
    }
    assert rounds == expected_rounds, f"想定と異なる回次構成です: {sorted(rounds)}"
    assert len(rows) == 44, f"レコード数(行単位)が想定と異なります: {len(rows)}件"


def test_award_books_akutagawa_naoki_award_no_required():
    """芥川賞・直木賞は日本文学振興会公式サイトで全件回次(award_no)が確認できるため、
    award_no=Noneのエントリが混入したら検知する。"""
    missing = [t for t in _AWARD_BOOKS_SEED if t[0] in ("芥川賞", "直木賞") and t[1] is None]
    assert not missing, f"芥川賞・直木賞でaward_noが欠落しているエントリがあります: {missing}"


def test_award_books_seeds_min_round_boundary():
    """芥川賞・直木賞のseeds.py最小award_noがmigrations.AWARD_BOOKS_SEEDS_MIN_ROUNDと一致するか確認する。
    この境界値はPLAM CSV由来の1935〜2002年データとの復元マイグレーションが前提とする境界であり、
    ズレるとPLAM側データの復元漏れ・二重挿入につながる。"""
    for award, expected_min in AWARD_BOOKS_SEEDS_MIN_ROUND.items():
        rows = [t for t in _AWARD_BOOKS_SEED if t[0] == award and t[1] is not None]
        actual_min = min(t[1] for t in rows)
        assert actual_min == expected_min, (
            f"{award}のseeds.py最小award_noが{actual_min}ですが、"
            f"migrations.AWARD_BOOKS_SEEDS_MIN_ROUND={expected_min}と不一致です"
        )


def test_award_books_no_duplicate_entries():
    """award, award_year, title, author の組み合わせで重複がないか確認（award_noは含めない）。
    award_no違いだけの重複（例: 直木賞2024回のNone混入）を検出するため、キーに award_no を含めない。"""
    entries = [(t[0], t[2], t[3], t[4]) for t in _AWARD_BOOKS_SEED]
    seen = set()
    dups = []
    for e in entries:
        if e in seen:
            dups.append(e)
        seen.add(e)
    assert not dups, f"award_booksシードに重複エントリがあります: {dups}"

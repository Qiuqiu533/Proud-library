"""
services.integrity の不一致判定ロジックの回帰テスト。
2026-07-05: ISBN 9784488029364 が genre_books で別の本のデータのまま
登録されていた事故（librarylife.net/OpenBDは正しいのにDBだけ誤り）を
受けて追加したISBN整合性監査機能のテスト。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.integrity import _mismatch_fields


def test_mismatch_fields_detects_completely_different_book():
    """完全に別の本（今回の実際の事故と同じパターン）は不一致として検出する。"""
    fields = _mismatch_fields("すごい科学論文", "池谷 裕二", "カフェーの帰り道", "嶋津 輝")
    assert "title" in fields
    assert "author" in fields


def test_mismatch_fields_allows_minor_formatting_differences():
    """空白の有無・表記ゆれ程度では不一致と判定しない（誤検知防止）。"""
    fields = _mismatch_fields("世界99 <上>", "村田 沙耶香", "世界99<上>", "村田沙耶香")
    assert fields == []


def test_mismatch_fields_no_openbd_data_returns_empty():
    """OpenBD側にデータが無い場合は判定しない（誤検知防止）。"""
    fields = _mismatch_fields("何かの本", "誰か", "", "")
    assert fields == []


def test_mismatch_fields_author_only_mismatch():
    """タイトルは一致するが著者だけ異なる場合はauthorのみ検出する。"""
    fields = _mismatch_fields("同じタイトルの本", "田中太郎", "同じタイトルの本", "全然違う人物名")
    assert fields == ["author"]


def test_mismatch_fields_allows_series_and_label_suffix():
    """genre_books側がシリーズ名・文庫レーベル・巻数を含む表示用タイトルを
    保持していても、OpenBDの簡潔なタイトルと一致すると判定する
    （2026-07-06: 実データで1,182件中の大半がこのパターンの誤検知だった）。"""
    cases = [
        ("悪人(上) (朝日文庫)", "吉田 修一", "悪人 上", "吉田,修一,1968-"),
        ("連写 TOKAGE 特殊遊撃捜査隊 (朝日文庫)", "今野敏", "連写", "今野,敏,1955-"),
        ("魔球 (講談社文庫)", "東野 圭吾", "魔球", "東野,圭吾,1958-"),
        ("春の高瀬舟―御宿かわせみ〈24〉 (文春文庫)", "平岩 弓枝", "春の高瀬舟", "平岩,弓枝,1932-"),
    ]
    for db_t, db_a, ob_t, ob_a in cases:
        assert _mismatch_fields(db_t, db_a, ob_t, ob_a) == [], f"誤検知: {db_t} vs {ob_t}"


def test_mismatch_fields_allows_openbd_multi_contributor_author():
    """OpenBDが訳者・共著者等を生没年付きで複数列挙していても、DBの著者名が
    そのいずれかと一致すれば著者不一致にしない。"""
    fields = _mismatch_fields(
        "スノーモンキー (とんぼの本)", "岩合 光昭",
        "スノーモンキー", "岩合,光昭,1950- 岩合,日出子,1944-"
    )
    assert fields == []

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

"""
services.awards._strip_volume_suffix / _sync_awards_from_master の
上下巻タイトル表記揺れ対応の回帰テスト。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.awards import _strip_volume_suffix


def test_strip_volume_suffix_removes_common_patterns():
    cases = [
        ("世界99（上・下）", "世界99"),
        ("世界99 <上>", "世界99"),
        ("世界99 <下>", "世界99"),
        ("洪水はわが魂に及び（上・下）", "洪水はわが魂に及び"),
        ("土の記（上・下）", "土の記"),
        ("土の記 <上>", "土の記"),
    ]
    for raw, expected in cases:
        assert _strip_volume_suffix(raw) == expected, f"{raw!r} -> {_strip_volume_suffix(raw)!r} (expected {expected!r})"


def test_strip_volume_suffix_no_change_when_no_suffix():
    """巻数表記が無いタイトルは変化しない（誤って本文中の「上」「下」を消さない）。"""
    cases = ["みいら採り猟奇譚", "侍", "ミトンとふびん", "上を向いて歩こう"]
    for title in cases:
        assert _strip_volume_suffix(title) == title

"""
services/utils.py のユニットテスト。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.utils import _hira_to_kata, _kata_to_hira, _hash_password, _verify_password
from services.awards import _normalize_pubdate


def test_hira_to_kata():
    assert _hira_to_kata("あいうえお") == "アイウエオ"
    assert _hira_to_kata("かきくけこ") == "カキクケコ"
    assert _hira_to_kata("ABC") == "ABC"       # ASCII はそのまま
    assert _hira_to_kata("") == ""


def test_kata_to_hira():
    assert _kata_to_hira("アイウエオ") == "あいうえお"
    assert _kata_to_hira("カキクケコ") == "かきくけこ"
    assert _kata_to_hira("ABC") == "ABC"
    assert _kata_to_hira("") == ""


def test_hira_kata_roundtrip():
    hira = "さしすせそたちつてとなにぬねの"
    assert _kata_to_hira(_hira_to_kata(hira)) == hira


def test_normalize_pubdate_yyyymm():
    assert _normalize_pubdate("202301") == "2023-01"
    assert _normalize_pubdate("200612") == "2006-12"


def test_normalize_pubdate_yyyymmdd():
    assert _normalize_pubdate("20230315") == "2023-03"


def test_normalize_pubdate_with_hyphen():
    assert _normalize_pubdate("2023-01") == "2023-01"


def test_normalize_pubdate_empty():
    assert _normalize_pubdate("") == ""
    assert _normalize_pubdate(None) == ""


def test_hash_and_verify_password():
    h, s = _hash_password("testpass")
    assert _verify_password("testpass", h, s) is True
    assert _verify_password("wrongpass", h, s) is False


def test_hash_different_salts():
    h1, s1 = _hash_password("same")
    h2, s2 = _hash_password("same")
    # 異なるsaltで異なるハッシュ
    assert s1 != s2
    assert h1 != h2

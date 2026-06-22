"""
services/utils.py のユニットテスト。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.utils import _hira_to_kata, _kata_to_hira, _hash_password, _verify_password, _is_bcrypt_hash
from services.awards import _normalize_pubdate
import hashlib, secrets


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


def test_hash_is_bcrypt():
    h, s = _hash_password("testpass")
    assert _is_bcrypt_hash(h), "新規ハッシュは bcrypt 形式である必要があります"
    assert s == "", "bcrypt は salt を内包するため空文字を返す"


def test_bcrypt_verify_correct():
    h, s = _hash_password("testpass")
    assert _verify_password("testpass", h, s) is True


def test_bcrypt_verify_wrong():
    h, s = _hash_password("testpass")
    assert _verify_password("wrongpass", h, s) is False


def test_bcrypt_different_hashes():
    """同じパスワードでも毎回異なるハッシュ（bcrypt の salt ランダム化）。"""
    h1, _ = _hash_password("same")
    h2, _ = _hash_password("same")
    assert h1 != h2


def test_backward_compat_sha256():
    """旧 SHA-256 ハッシュも引き続き検証できること（後方互換）。"""
    salt = secrets.token_hex(16)
    old_hash = hashlib.sha256((salt + "oldpass").encode()).hexdigest()
    assert not _is_bcrypt_hash(old_hash)
    assert _verify_password("oldpass", old_hash, salt) is True
    assert _verify_password("wrong", old_hash, salt) is False

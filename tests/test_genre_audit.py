"""
services.books の genre/NDC 整合性監査の回帰テスト。
2026-07-12: 「風姿花伝」（NDC773・能楽）がNDC_TO_GENREマッピングに未対応
だったため「ミステリ・推理」に誤分類されていた事故を受けて追加。
自動修復はせず、検出のみ行う設計を検証する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_con, execute
from services.books import (
    _classify_genre, audit_genre_ndc_mismatches, data_quality_summary, list_books_missing_ndc,
)

_TEST_ISBN_MISMATCH = "9999900000301"
_TEST_ISBN_MATCH = "9999900000302"


def _cleanup():
    con = get_con()
    for isbn in (_TEST_ISBN_MISMATCH, _TEST_ISBN_MATCH):
        execute(con, "DELETE FROM genre_books WHERE isbn=?", (isbn,))
    con.commit()
    con.close()


def test_classify_genre_maps_773_to_essay_not_mystery():
    """NDC773（能楽）は「エッセイ・評論」に分類され、「ミステリ・推理」にはならない
    （風姿花伝の誤分類事故の直接的な回帰テスト）。"""
    genre = _classify_genre("773", "風姿花伝", "")
    assert genre == "エッセイ・評論"
    assert genre != "ミステリ・推理"


def test_classify_genre_maps_770s_range():
    for ndc in ["770", "771", "774", "779"]:
        assert _classify_genre(ndc, "テスト", "") == "エッセイ・評論"


def test_audit_genre_ndc_mismatches_detects_stale_genre():
    """ndcは正しいのにgenreが古い（現在のマッピングと矛盾する）本を検出する。"""
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, ndc) "
            "VALUES (?,?,?,?,?,?,?)",
            (_TEST_ISBN_MISMATCH, "テスト能楽書", "テスト著者", "テスト出版社", "ミステリ・推理", "その他", "773"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, ndc) "
            "VALUES (?,?,?,?,?,?,?)",
            (_TEST_ISBN_MATCH, "テスト文芸書", "テスト著者", "テスト出版社", "文芸小説", "その他", "913"))
    con.commit()
    con.close()
    try:
        mismatches = audit_genre_ndc_mismatches(limit=1000)
        isbns = {m["isbn"] for m in mismatches}
        assert _TEST_ISBN_MISMATCH in isbns
        assert _TEST_ISBN_MATCH not in isbns

        target = next(m for m in mismatches if m["isbn"] == _TEST_ISBN_MISMATCH)
        assert target["current_genre"] == "ミステリ・推理"
        assert target["suggested_genre"] == "エッセイ・評論"
    finally:
        _cleanup()


def test_audit_genre_ndc_mismatches_ignores_books_without_ndc():
    """ndcが未設定の本は監査対象に含めない（判定材料がないため）。"""
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_MISMATCH, "テスト本", "テスト著者", "テスト出版社", "ミステリ・推理", "その他"))
    con.commit()
    con.close()
    try:
        mismatches = audit_genre_ndc_mismatches(limit=1000)
        isbns = {m["isbn"] for m in mismatches}
        assert _TEST_ISBN_MISMATCH not in isbns
    finally:
        _cleanup()


def test_data_quality_summary_counts_missing_ndc():
    """2026-07-12: 「風姿花伝」「歴史探偵忘れ残りの記」がいずれもndc空のため
    audit_genre_ndc_mismatchesの対象外だった（監査の死角）。この死角を
    可視化するdata_quality_summary()の回帰テスト。"""
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_MISMATCH, "NDC欠落テスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, ndc) "
            "VALUES (?,?,?,?,?,?,?)",
            (_TEST_ISBN_MATCH, "NDC取得済みテスト本", "テスト著者", "テスト出版社", "文芸小説", "その他", "913"))
    con.commit()
    con.close()
    try:
        summary = data_quality_summary()
        assert summary["total_books"] >= 2
        assert summary["ndc_missing_count"] >= 1
        assert summary["ndc_present_count"] >= 1
        assert "ndc_unmapped_count" in summary
    finally:
        _cleanup()


def test_list_books_missing_ndc_returns_only_missing():
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_MISMATCH, "NDC欠落テスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, ndc) "
            "VALUES (?,?,?,?,?,?,?)",
            (_TEST_ISBN_MATCH, "NDC取得済みテスト本", "テスト著者", "テスト出版社", "文芸小説", "その他", "913"))
    con.commit()
    con.close()
    try:
        books = list_books_missing_ndc(limit=100000)
        isbns = {b["isbn"] for b in books}
        assert _TEST_ISBN_MISMATCH in isbns
        assert _TEST_ISBN_MATCH not in isbns
    finally:
        _cleanup()

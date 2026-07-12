"""
services.books の genre/NDC 整合性監査の回帰テスト。
2026-07-12: 「風姿花伝」（NDC773・能楽）がNDC_TO_GENREマッピングに未対応
だったため「ミステリ・推理」に誤分類されていた事故を受けて追加。
自動修復はせず、検出のみ行う設計を検証する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_con, execute, fetchone
import services.books as books_module
from services.books import (
    _classify_genre, audit_genre_ndc_mismatches, data_quality_summary, list_books_missing_ndc,
    run_ndc_backfill, is_ndc_backfill_running, get_ndc_backfill_last_result,
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


def test_data_quality_summary_counts_invalid_isbn():
    """978/979始まりの13桁でないISBN（librarylife.netの仮ISBN等）を
    invalid_isbn_countとして別集計する。"""
    isbn_invalid = "00"
    isbn_valid = "9789900000601"
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (isbn_invalid, "仮ISBNテスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (isbn_valid, "有効ISBNテスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        summary = data_quality_summary()
        assert summary["invalid_isbn_count"] >= 1
    finally:
        con = get_con()
        for isbn in (isbn_invalid, isbn_valid):
            execute(con, "DELETE FROM genre_books WHERE isbn=?", (isbn,))
        con.commit()
        con.close()


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


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_run_ndc_backfill_classifies_results_by_reason(monkeypatch):
    """2026-07-12: NDC補完バッチの回帰テスト。取得成功・OpenBDにデータなし・
    OpenBDにNDCなしを理由別に正しく集計し、成功分のみndc/genreを更新する。"""
    import time as time_module

    isbn_success = "9789900000401"   # NDC取得できジャンルも変わる（有効なISBN-13形式）
    isbn_no_data = "9789900000402"   # OpenBDに該当データなし（有効なISBN-13形式）
    isbn_no_ndc = "9789900000403"    # OpenBDにデータはあるがNDCなし（有効なISBN-13形式）

    con = get_con()
    for isbn in (isbn_success, isbn_no_data, isbn_no_ndc):
        execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
                "VALUES (?,?,?,?,?,?)",
                (isbn, "テスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()

    def _fake_get(url, params=None, timeout=None):
        isbns = params["isbn"].split(",")
        payload = []
        for isbn in isbns:
            if isbn == isbn_success:
                payload.append({
                    "onix": {"DescriptiveDetail": {"Subject": [
                        {"SubjectSchemeIdentifier": "78", "SubjectCode": "913"}
                    ]}}
                })
            elif isbn == isbn_no_ndc:
                payload.append({"onix": {"DescriptiveDetail": {}}})
            else:
                payload.append(None)
        return _FakeResponse(payload)

    monkeypatch.setattr(books_module.requests, "get", _fake_get)
    try:
        result, code = run_ndc_backfill("テスト太郎")
        assert code == 200
        assert result["status"] == "started"

        for _ in range(50):
            if not is_ndc_backfill_running():
                break
            time_module.sleep(0.1)
        else:
            raise AssertionError("NDC補完がタイムアウトしました")

        last = get_ndc_backfill_last_result()
        assert last is not None
        assert "error" not in last
        assert last["success"] >= 1
        assert last["no_data_in_openbd"] >= 1
        assert last["no_ndc_in_openbd"] >= 1

        con = get_con()
        row = fetchone(con, "SELECT ndc, genre FROM genre_books WHERE isbn=?", (isbn_success,))
        no_data_row = fetchone(con, "SELECT ndc FROM genre_books WHERE isbn=?", (isbn_no_data,))
        con.close()
        assert row["ndc"] == "913"
        assert row["genre"] == "文芸小説"
        assert no_data_row["ndc"] in (None, "")
    finally:
        con = get_con()
        for isbn in (isbn_success, isbn_no_data, isbn_no_ndc):
            execute(con, "DELETE FROM genre_books WHERE isbn=?", (isbn,))
        con.commit()
        con.close()


def test_run_ndc_backfill_skips_invalid_isbns(monkeypatch):
    """2026-07-12: 本番でlimit=200の試験実行を行った際、昇順ソートの先頭に
    librarylife.netの仮ISBN（"00"等、978/979始まりの13桁でない）が集中し、
    全件がno_data_in_openbdになった。仮ISBNはOpenBDに存在しえないため、
    NDC補完の対象から除外する回帰テスト。"""
    import time as time_module

    isbn_invalid = "00"  # 実際に本番で観測された仮ISBNのパターン
    isbn_valid = "9789900000501"

    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (isbn_invalid, "仮ISBNテスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (isbn_valid, "有効ISBNテスト本", "テスト著者", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()

    called_isbns = []

    def _fake_get(url, params=None, timeout=None):
        isbns = params["isbn"].split(",")
        called_isbns.extend(isbns)
        return _FakeResponse([None for _ in isbns])

    monkeypatch.setattr(books_module.requests, "get", _fake_get)
    try:
        result, code = run_ndc_backfill("テスト太郎")
        assert code == 200

        for _ in range(50):
            if not is_ndc_backfill_running():
                break
            time_module.sleep(0.1)
        else:
            raise AssertionError("NDC補完がタイムアウトしました")

        assert isbn_invalid not in called_isbns
    finally:
        con = get_con()
        for isbn in (isbn_invalid, isbn_valid):
            execute(con, "DELETE FROM genre_books WHERE isbn=?", (isbn,))
        con.commit()
        con.close()


def test_run_ndc_backfill_rejects_concurrent_run(monkeypatch):
    monkeypatch.setattr(books_module, "_ndc_backfill_running", True)
    try:
        result, code = run_ndc_backfill("テスト太郎")
        assert code == 409
    finally:
        books_module._ndc_backfill_running = False

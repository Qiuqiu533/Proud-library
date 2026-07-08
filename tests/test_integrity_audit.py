"""
services.integrity の不一致判定ロジックの回帰テスト。
2026-07-05: ISBN 9784488029364 が genre_books で別の本のデータのまま
登録されていた事故（librarylife.net/OpenBDは正しいのにDBだけ誤り）を
受けて追加したISBN整合性監査機能のテスト。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.integrity import (
    _mismatch_fields, severity_info, bulk_repair_by_level, dashboard_summary,
    backfill_clear_stale_ai_reviews,
)
from database import get_con, execute, fetchone


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


def test_mismatch_fields_allows_short_title_containment():
    """2文字タイトル（例:「無明」「地球」）でも、副題・シリーズ名を含む長い
    タイトルとの包含関係で一致と判定する（2026-07-06: 実データで検出漏れ判明）。"""
    fields = _mismatch_fields("無明", "今野 敏", "無明　警視庁強行犯係・樋口顕", "今野敏")
    assert "title" not in fields


def test_mismatch_fields_case_insensitive_title():
    """英数字部分の大文字小文字差だけでは不一致と判定しない。"""
    fields = _mismatch_fields("1Q84 BOOK 2", "村上 春樹", "1Q84 book 2", "村上,春樹,1949-")
    assert "title" not in fields


def test_severity_info_critical_for_title_and_author_mismatch():
    """タイトル・著者とも不一致は実データ検証でほぼ100%本物の異常だったため
    Critical（最優先）とする。"""
    info = severity_info(["title", "author"])
    assert info["level"] == "critical"
    assert info["score"] == 100


def test_severity_info_warning_for_title_only():
    info = severity_info(["title"])
    assert info["level"] == "warning"


def test_severity_info_info_for_author_only():
    """著者のみ不一致は実データ検証でほぼ100%表記ゆれだったためInfo（参考情報）とする。"""
    info = severity_info(["author"])
    assert info["level"] == "info"


_TEST_ISBN_CRITICAL = "9999900000001"
_TEST_ISBN_INFO = "9999900000002"


def _seed_bulk_repair_fixture():
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_CRITICAL, "すごい科学論文", "池谷 裕二", "新潮社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_INFO, "同じタイトル", "田中太郎", "出版社A", "その他", "その他"))
    execute(con, """INSERT OR REPLACE INTO integrity_findings
        (isbn, db_title, db_author, db_publisher, openbd_title, openbd_author, openbd_publisher, mismatch_fields, resolved)
        VALUES (?,?,?,?,?,?,?,?,0)""",
        (_TEST_ISBN_CRITICAL, "すごい科学論文", "池谷 裕二", "新潮社", "カフェーの帰り道", "嶋津,輝,1969-", "東京創元社", "title,author"))
    execute(con, """INSERT OR REPLACE INTO integrity_findings
        (isbn, db_title, db_author, db_publisher, openbd_title, openbd_author, openbd_publisher, mismatch_fields, resolved)
        VALUES (?,?,?,?,?,?,?,?,0)""",
        (_TEST_ISBN_INFO, "同じタイトル", "田中太郎", "出版社A", "同じタイトル", "全然違う人", "出版社A", "author"))
    con.commit()
    con.close()


def _cleanup_bulk_repair_fixture():
    con = get_con()
    for isbn in (_TEST_ISBN_CRITICAL, _TEST_ISBN_INFO):
        execute(con, "DELETE FROM genre_books WHERE isbn=?", (isbn,))
        execute(con, "DELETE FROM integrity_findings WHERE isbn=?", (isbn,))
        execute(con, "DELETE FROM integrity_log WHERE isbn=?", (isbn,))
    con.commit()
    con.close()


def test_bulk_repair_by_level_only_touches_specified_level():
    """bulk_repair_by_levelはcriticalのみを対象にし、infoレベルには触れない。
    2026-07-07: 191件の同期一括処理でタイムアウトによる500エラーが発生した
    事故を受けてバックグラウンドスレッド実行に変更したため、完了をポーリングで待つ。"""
    import time
    from services.integrity import is_bulk_repair_running, get_bulk_repair_last_result

    _seed_bulk_repair_fixture()
    try:
        result, code = bulk_repair_by_level("critical", "テスト太郎")
        assert code == 200
        assert result["status"] == "started"

        for _ in range(50):
            if not is_bulk_repair_running():
                break
            time.sleep(0.1)
        else:
            raise AssertionError("一括修復がタイムアウトしました")

        last = get_bulk_repair_last_result()
        assert last is not None
        assert last["repaired"] == 1

        con = get_con()
        repaired_row = fetchone(con, "SELECT * FROM genre_books WHERE isbn=?", (_TEST_ISBN_CRITICAL,))
        untouched_row = fetchone(con, "SELECT * FROM genre_books WHERE isbn=?", (_TEST_ISBN_INFO,))
        con.close()
        assert repaired_row["title"] == "カフェーの帰り道"
        assert repaired_row["author"] == "嶋津,輝,1969-"
        assert untouched_row["title"] == "同じタイトル"
        assert untouched_row["author"] == "田中太郎"
    finally:
        _cleanup_bulk_repair_fixture()


def test_backfill_clear_stale_ai_reviews_clears_only_repaired_books():
    """title/authorがintegrity_logで修復済みの本だけAI書評フィールドをクリアし、
    ai_review_content処理済みのものは対象から除外する（二重処理防止）。
    2026-07-08: 194件の同期処理でgunicornワーカーがタイムアウト→SIGKILLされ
    500エラーになった事故を受けてバックグラウンドスレッド実行に変更したため、
    完了をポーリングで待つ。"""
    import time
    from services.integrity import is_backfill_ai_clear_running, get_backfill_ai_clear_last_result

    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, description, ai_summary) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_TEST_ISBN_CRITICAL, "カフェーの帰り道", "嶋津,輝,1969-", "東京創元社", "その他", "その他",
             "すごい科学論文の説明文", "すごい科学論文の要約"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, description, ai_summary) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_TEST_ISBN_INFO, "同じタイトル", "田中太郎", "出版社A", "その他", "その他",
             "既に処理済みの説明文", "既に処理済みの要約"))
    execute(con, "INSERT INTO integrity_log (isbn, field, before_value, after_value, operator, reason) VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_CRITICAL, "title", "すごい科学論文", "カフェーの帰り道", "テスト太郎", "テスト修復"))
    execute(con, "INSERT INTO integrity_log (isbn, field, before_value, after_value, operator, reason) VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_INFO, "title", "旧タイトル", "同じタイトル", "テスト太郎", "テスト修復"))
    execute(con, "INSERT INTO integrity_log (isbn, field, before_value, after_value, operator, reason) VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_INFO, "ai_review_content", "(旧タイトルに基づく内容)", "(クリア・再生成待ち)", "テスト太郎", "既に処理済み"))
    con.commit()
    con.close()

    try:
        result, code = backfill_clear_stale_ai_reviews("テスト太郎")
        assert code == 200
        assert result["status"] == "started"

        for _ in range(50):
            if not is_backfill_ai_clear_running():
                break
            time.sleep(0.1)
        else:
            raise AssertionError("backfill_clear_stale_ai_reviewsがタイムアウトしました")

        last = get_backfill_ai_clear_last_result()
        assert last is not None
        assert last["cleared"] == 1

        con = get_con()
        cleared_row = fetchone(con, "SELECT * FROM genre_books WHERE isbn=?", (_TEST_ISBN_CRITICAL,))
        untouched_row = fetchone(con, "SELECT * FROM genre_books WHERE isbn=?", (_TEST_ISBN_INFO,))
        con.close()
        assert cleared_row["description"] is None
        assert cleared_row["ai_summary"] is None
        assert untouched_row["description"] == "既に処理済みの説明文"
        assert untouched_row["ai_summary"] == "既に処理済みの要約"
    finally:
        _cleanup_bulk_repair_fixture()


def test_dashboard_summary_reflects_unresolved_counts():
    _seed_bulk_repair_fixture()
    try:
        summary = dashboard_summary()
        assert summary["critical_count"] >= 1
        assert summary["info_count"] >= 1
        assert 0 <= summary["health_score"] <= 100
        assert "total_books" in summary
    finally:
        _cleanup_bulk_repair_fixture()

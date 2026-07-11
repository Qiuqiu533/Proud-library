"""
services.ai_review_generator の回帰テスト。
2026-07-08: AI書評再生成基盤（Phase 1: 管理画面からの半自動実行）追加に伴い、
実際のOpenAI API呼び出しは行わず、対象抽出・コスト概算・安全装置
（APIキー未設定時のガード・1ジョブ上限）のみを検証する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_con, execute
import services.ai_review_generator as ai_review_generator

_TEST_ISBN = "9999900000099"


def _seed_book(description=None):
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, description) "
            "VALUES (?,?,?,?,?,?,?)",
            (_TEST_ISBN, "テスト対象本", "テスト著者", "テスト出版社", "その他", "その他", description))
    con.commit()
    con.close()


def _cleanup():
    con = get_con()
    execute(con, "DELETE FROM genre_books WHERE isbn=?", (_TEST_ISBN,))
    con.commit()
    con.close()


def test_estimate_regeneration_counts_missing_description_as_target():
    """descriptionが未設定（NULL）の本は再生成対象としてカウントされる。"""
    _seed_book(description=None)
    try:
        result = ai_review_generator.estimate_regeneration(limit=100)
        assert result["target_count"] >= 1
        assert result["estimated_cost_jpy"] >= 0
        assert result["job_limit"] == 100
    finally:
        _cleanup()


def test_estimate_regeneration_excludes_books_with_long_description():
    """十分な長さのdescriptionがある本は再生成対象に含まれない。"""
    _seed_book(description="x" * 200)
    try:
        con = get_con()
        from database import fetchone
        row = fetchone(con, "SELECT description FROM genre_books WHERE isbn=?", (_TEST_ISBN,))
        con.close()
        assert row["description"] == "x" * 200

        result = ai_review_generator.estimate_regeneration(limit=1000)
        targets = ai_review_generator._fetch_regeneration_targets(1000)
        isbns = [t["isbn"] for t in targets]
        assert _TEST_ISBN not in isbns
    finally:
        _cleanup()


def test_estimate_regeneration_respects_job_limit():
    """limitがJOB_MAX_LIMIT（100）を超えても100件に丸められる。"""
    result = ai_review_generator.estimate_regeneration(limit=9999)
    assert result["job_limit"] == 100


def test_start_regeneration_fails_without_api_key(monkeypatch):
    """OPENAI_API_KEYが未設定の場合、OpenAIを呼ばずに400エラーで即座に終了する
    （DeepSeekでの想定外課金の反省を踏まえた安全装置）。"""
    monkeypatch.setattr(ai_review_generator, "OPENAI_API_KEY", "")
    result, code = ai_review_generator.start_regeneration(50, "テスト太郎")
    assert code == 400
    assert "APIキー" in result["error"]
    assert not ai_review_generator.is_regeneration_running()


def test_start_regeneration_rejects_concurrent_run(monkeypatch):
    """既に実行中の場合は409を返し、二重起動を防止する。"""
    monkeypatch.setattr(ai_review_generator, "OPENAI_API_KEY", "dummy-key")
    monkeypatch.setattr(ai_review_generator, "_regen_running", True)
    try:
        result, code = ai_review_generator.start_regeneration(50, "テスト太郎")
        assert code == 409
    finally:
        ai_review_generator._regen_running = False


def test_start_regeneration_with_isbn_targets_only_that_book(monkeypatch):
    """isbn指定時はその1冊だけを対象にする（未生成分の条件を無視する）。
    2026-07-09: _run()内のループ変数isbnが引数isbnをシャドーイングし、
    `if isbn:` 判定で UnboundLocalError が発生するバグがあったための回帰テスト。"""
    import time as time_module

    _seed_book(description="x" * 200)  # 通常の未生成分クエリからは除外される状態
    calls = []

    def _fake_regenerate_one(isbn, book, min_score=70):
        calls.append(isbn)
        return {"ok": True}

    monkeypatch.setattr(ai_review_generator, "OPENAI_API_KEY", "dummy-key")
    monkeypatch.setattr(ai_review_generator, "regenerate_one", _fake_regenerate_one)
    try:
        result, code = ai_review_generator.start_regeneration(100, "テスト太郎", isbn=_TEST_ISBN)
        assert code == 200

        for _ in range(50):
            if not ai_review_generator.is_regeneration_running():
                break
            time_module.sleep(0.1)
        else:
            raise AssertionError("isbn指定の再生成がタイムアウトしました")

        last = ai_review_generator.get_regeneration_last_result()
        assert last is not None
        assert "error" not in last
        assert calls == [_TEST_ISBN]
        assert last["target_count"] == 1
        assert last["success"] == 1
    finally:
        _cleanup()

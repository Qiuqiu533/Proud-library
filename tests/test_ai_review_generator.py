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


def test_regenerate_one_persists_confidence(monkeypatch):
    """2026-07-11: confidenceは生成時の足切り判定にのみ使い保存していなかった
    ため、35冊検証で分布を事後集計できなかった。ai_review_confidence列に
    保存されることを確認する回帰テスト。"""
    from database import fetchone

    _seed_book(description=None)

    def _fake_generate_with_retry(title, author, publisher, genre, wiki_info, min_score=70, series="", blurb="",
                                   isbn="", pubdate="", awards_text=""):
        return {"review": "テストレビュー本文です。" * 5, "summary": "テスト一言", "tags": ["タグ1"], "score": 85, "confidence": 72}

    monkeypatch.setattr(ai_review_generator, "generate_with_retry", _fake_generate_with_retry)
    try:
        result = ai_review_generator.regenerate_one(_TEST_ISBN, {"title": "テスト対象本", "author": "テスト著者", "publisher": "", "genre": ""})
        assert result == {"ok": True}

        con = get_con()
        row = fetchone(con, "SELECT ai_review_confidence, ai_review_score FROM genre_books WHERE isbn=?", (_TEST_ISBN,))
        con.close()
        assert row["ai_review_confidence"] == 72
        assert row["ai_review_score"] == 85
    finally:
        _cleanup()


def test_regenerate_one_discards_result_failing_quality_check(monkeypatch):
    """2026-07-12: 生成後の品質チェック（ジャンル不整合検出）により、
    「風姿花伝」クラスの誤生成が保存されずreasonで破棄されることを確認する。"""
    from database import fetchone

    _seed_book(description="既存の説明文")

    def _fake_generate_with_retry(title, author, publisher, genre, wiki_info, min_score=70, series="", blurb="",
                                   isbn="", pubdate="", awards_text=""):
        return {
            "review": "本作はミステリ小説として、巧妙な謎解きが楽しめる一冊です。" * 2,
            "summary": "テスト一言", "tags": ["タグ1"], "score": 85, "confidence": 90,
        }

    monkeypatch.setattr(ai_review_generator, "generate_with_retry", _fake_generate_with_retry)
    try:
        result = ai_review_generator.regenerate_one(
            _TEST_ISBN, {"title": "風姿花伝", "author": "世阿弥", "publisher": "", "genre": "エッセイ・評論"})
        assert result["ok"] is False
        assert "品質チェックNG" in result["reason"]

        con = get_con()
        row = fetchone(con, "SELECT description FROM genre_books WHERE isbn=?", (_TEST_ISBN,))
        con.close()
        assert row["description"] == "既存の説明文"
    finally:
        _cleanup()


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


def test_opening_pattern_for_isbn_is_deterministic():
    """同じISBNは常に同じ書き出しパターンを返す（再生成しても結果がぶれない）。"""
    p1 = ai_review_generator._opening_pattern_for_isbn("9784000044677")
    p2 = ai_review_generator._opening_pattern_for_isbn("9784000044677")
    assert p1 == p2
    assert p1 in ai_review_generator.OPENING_PATTERNS


def test_opening_pattern_varies_across_isbns():
    """異なるISBNでは（十分な数を試せば）異なる書き出しパターンが選ばれる。"""
    patterns = {ai_review_generator._opening_pattern_for_isbn(f"999990000{i:04d}") for i in range(20)}
    assert len(patterns) > 1


def test_confidence_distribution_empty_when_no_data():
    """confidenceが1件も保存されていない場合はtotal_count=0を返す。"""
    result = ai_review_generator.confidence_distribution()
    assert "total_count" in result
    assert "buckets" in result


def test_confidence_distribution_buckets_and_average():
    """保存済みconfidence値が正しい帯域に分類され、平均が計算される。"""
    con = get_con()
    isbns = ["9999900000201", "9999900000202", "9999900000203"]
    confidences = [62, 75, 95]
    for isbn, conf in zip(isbns, confidences):
        execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format, ai_review_confidence) "
                "VALUES (?,?,?,?,?,?,?)",
                (isbn, "テスト本", "テスト著者", "テスト出版社", "その他", "その他", conf))
    con.commit()
    con.close()
    try:
        result = ai_review_generator.confidence_distribution()
        assert result["total_count"] >= 3
        assert result["buckets"]["60-64"] >= 1
        assert result["buckets"]["70-79"] >= 1
        assert result["buckets"]["90-100"] >= 1
    finally:
        con = get_con()
        for isbn in isbns:
            execute(con, "DELETE FROM genre_books WHERE isbn=?", (isbn,))
        con.commit()
        con.close()


def test_format_pubdate_extracts_year():
    assert ai_review_generator._format_pubdate("201609") == "2016年"
    assert ai_review_generator._format_pubdate("") == ""
    assert ai_review_generator._format_pubdate("20") == ""


def test_format_awards_formats_json_list():
    """2026-07-11: 書誌情報拡充で追加。award_books由来の受賞歴（自前の検証済み
    データ）をプロンプトへ渡すための整形関数。"""
    import json as json_module
    awards_json = json_module.dumps([
        {"award": "本屋大賞", "year": 2017, "rank": 1},
        {"award": "直木賞", "year": 2017},
    ], ensure_ascii=False)
    result = ai_review_generator._format_awards(awards_json)
    assert "2017年本屋大賞（1位）" in result
    assert "2017年直木賞" in result


def test_format_awards_handles_empty_and_invalid():
    assert ai_review_generator._format_awards(None) == ""
    assert ai_review_generator._format_awards("") == ""
    assert ai_review_generator._format_awards("[]") == ""
    assert ai_review_generator._format_awards("not json") == ""


def test_format_awards_accepts_list_directly():
    result = ai_review_generator._format_awards([{"award": "芥川賞", "year": 2020}])
    assert result == "2020年芥川賞"

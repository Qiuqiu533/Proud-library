"""
services.plam の類似作品推薦（get_related_works）の回帰テスト。
2026-07-14: v1.2 Phase1。純粋なPLAMスコア順だと、蔵書に無い作品ばかりが
上位を占めクリックできない推薦になってしまう事故（実測でin_library率0%の
ケースを複数確認）を受けて、蔵書内の候補を優先する2段階選定に変更した。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_con, execute
import services.plam as plam_module

_TEST_ISBN = "9999900000901"


def _seed_fixture(monkeypatch, matched_title="蔵書にある本"):
    """award_history.csv上で同スコアの3候補（W2,W3,W4）を用意し、W4だけが
    genre_booksに存在する（＝蔵書内）状態を作る。"""
    fixtures = {
        "awards_master.csv": [
            {"award_id": "AKU", "award_name": "芥川賞", "weight": "100", "data_status": "done"},
        ],
        "cluster_summary.csv": [
            {"award_id": "AKU", "cluster_id": "literary"},
        ],
        "works.csv": [
            {"work_id": "W1", "canonical_title": "対象作品", "author": "著者A"},
            {"work_id": "W2", "canonical_title": "蔵書外の本1", "author": "著者B"},
            {"work_id": "W3", "canonical_title": "蔵書外の本2", "author": "著者C"},
            {"work_id": "W4", "canonical_title": matched_title, "author": "著者D"},
        ],
        "award_history.csv": [
            {"work_id": "W1", "award_id": "AKU", "award_year": "2020", "award_no": "1", "status": "awarded"},
            {"work_id": "W2", "award_id": "AKU", "award_year": "2019", "award_no": "2", "status": "awarded"},
            {"work_id": "W3", "award_id": "AKU", "award_year": "2018", "award_no": "3", "status": "awarded"},
            {"work_id": "W4", "award_id": "AKU", "award_year": "2017", "award_no": "4", "status": "awarded"},
        ],
        "bridge_works.csv": [],
        "award_similarity.csv": [],
    }

    def _fake_read(filename):
        return fixtures.get(filename, [])

    monkeypatch.setattr(plam_module, "_read", _fake_read)
    # lru_cacheをクリアして次回呼び出しでフィクスチャを読み直させる
    for fn in (plam_module._awards_master, plam_module._cluster_map, plam_module._works_index,
               plam_module._history_by_work, plam_module._bridge_set, plam_module._jaccard_map):
        fn.cache_clear()


def _cleanup_caches():
    for fn in (plam_module._awards_master, plam_module._cluster_map, plam_module._works_index,
               plam_module._history_by_work, plam_module._bridge_set, plam_module._jaccard_map):
        fn.cache_clear()


def test_related_works_prioritizes_in_library_candidate_over_equal_score_ones(monkeypatch):
    """W2,W3,W4は全て同スコア（芥川賞1件のみ共有）。W4だけをgenre_booksに
    投入した状態でlimit=2を指定すると、CSV順ではW2,W3が先に来るはずだが、
    在庫優先ロジックによりW4が結果に含まれることを確認する。"""
    _seed_fixture(monkeypatch)
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN, "蔵書にある本", "著者D", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        result = plam_module.get_related_works("W1", limit=2)
        result_wids = [r["work_id"] for r in result]
        assert "W4" in result_wids, f"在庫内候補W4が結果に含まれていない: {result_wids}"

        w4_entry = next(r for r in result if r["work_id"] == "W4")
        assert w4_entry["in_library"] is True
        assert w4_entry["isbn"] == _TEST_ISBN
    finally:
        con = get_con()
        execute(con, "DELETE FROM genre_books WHERE isbn=?", (_TEST_ISBN,))
        con.commit()
        con.close()
        _cleanup_caches()


def test_related_works_falls_back_to_non_library_when_insufficient(monkeypatch):
    """蔵書内候補が0件の場合は、従来通りスコア順の蔵書外候補で埋める。"""
    _seed_fixture(monkeypatch, matched_title="誰も持っていない本")
    try:
        result = plam_module.get_related_works("W1", limit=2)
        assert len(result) == 2
        assert all(r["in_library"] is False for r in result)
    finally:
        _cleanup_caches()

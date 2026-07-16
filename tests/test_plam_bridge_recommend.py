"""
services.plam.get_bridge_recommendations の回帰テスト。
2026-07-16: v1.2 Phase4。Bridge Works（ジャンル横断作品）を起点に、
利用者の読書の幅を広げる発見コーナー向けのレコメンド機能。
Phase1と同じ方針で、蔵書に無い本を勧めても意味が無いため蔵書内のみに絞る。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_con, execute
import services.plam as plam_module

_TEST_ISBN_A = "9999900000911"
_TEST_ISBN_B = "9999900000912"


def _seed_fixture(monkeypatch):
    fixtures = {
        "bridge_works.csv": [
            {"work_id": "B1", "title": "蔵書外の橋渡し作品", "author": "著者X",
             "bridge_type": "cross_cluster", "clusters": "literary mystery", "award_count": "5"},
            {"work_id": "B2", "title": "蔵書内の橋渡し作品A", "author": "著者Y",
             "bridge_type": "cross_cluster", "clusters": "literary mystery", "award_count": "3"},
            {"work_id": "B3", "title": "蔵書内の橋渡し作品B", "author": "著者Z",
             "bridge_type": "cross_cluster", "clusters": "mystery sf", "award_count": "2"},
            {"work_id": "B4", "title": "同一クラスタの橋渡し作品", "author": "著者W",
             "bridge_type": "intra_cluster", "clusters": "mystery", "award_count": "9"},
        ],
    }

    def _fake_read(filename):
        return fixtures.get(filename, [])

    monkeypatch.setattr(plam_module, "_read", _fake_read)


def test_bridge_recommendations_only_returns_in_library_cross_cluster_works(monkeypatch):
    """蔵書外（B1）・同一クラスタ（B4）は除外され、蔵書内のcross_cluster作品のみ返る。"""
    _seed_fixture(monkeypatch)
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_A, "蔵書内の橋渡し作品A", "著者Y", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_B, "蔵書内の橋渡し作品B", "著者Z", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        result = plam_module.get_bridge_recommendations(limit=5)
        titles = [r["title"] for r in result]
        assert "蔵書外の橋渡し作品" not in titles
        assert "同一クラスタの橋渡し作品" not in titles
        assert "蔵書内の橋渡し作品A" in titles
        assert "蔵書内の橋渡し作品B" in titles

        a = next(r for r in result if r["title"] == "蔵書内の橋渡し作品A")
        assert a["isbn"] == _TEST_ISBN_A
        assert a["cluster_labels"] == ["文学", "ミステリ"]
        assert a["reason"] == "文学×ミステリをつなぐ話題作です。"
    finally:
        con = get_con()
        execute(con, "DELETE FROM genre_books WHERE isbn IN (?,?)", (_TEST_ISBN_A, _TEST_ISBN_B))
        con.commit()
        con.close()


def test_bridge_recommendations_filters_by_cluster(monkeypatch):
    """2026-07-16: v1.3 Phase1。cluster指定で、そのジャンルに関係する
    Bridge Worksだけに絞り込めることを確認する（ジャンルページ向け）。"""
    _seed_fixture(monkeypatch)
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_A, "蔵書内の橋渡し作品A", "著者Y", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_B, "蔵書内の橋渡し作品B", "著者Z", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        # sf クラスタに関係するのはB4(intra_cluster除外済み)ではなくB3のみ
        result = plam_module.get_bridge_recommendations(limit=5, cluster="sf")
        titles = [r["title"] for r in result]
        assert titles == ["蔵書内の橋渡し作品B"]

        result_literary = plam_module.get_bridge_recommendations(limit=5, cluster="literary")
        titles_literary = [r["title"] for r in result_literary]
        assert "蔵書内の橋渡し作品A" in titles_literary
        assert "蔵書内の橋渡し作品B" not in titles_literary
    finally:
        con = get_con()
        execute(con, "DELETE FROM genre_books WHERE isbn IN (?,?)", (_TEST_ISBN_A, _TEST_ISBN_B))
        con.commit()
        con.close()


def test_bridge_recommendations_respects_limit_and_award_count_order(monkeypatch):
    """award_count（受賞数）が多い順に優先されることを確認する。"""
    _seed_fixture(monkeypatch)
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_A, "蔵書内の橋渡し作品A", "著者Y", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_B, "蔵書内の橋渡し作品B", "著者Z", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        result = plam_module.get_bridge_recommendations(limit=1)
        assert len(result) == 1
        assert result[0]["title"] == "蔵書内の橋渡し作品A"  # award_count=3 > B(2)
    finally:
        con = get_con()
        execute(con, "DELETE FROM genre_books WHERE isbn IN (?,?)", (_TEST_ISBN_A, _TEST_ISBN_B))
        con.commit()
        con.close()


def test_get_connected_genres_groups_by_mapped_genre_and_counts(monkeypatch):
    """2026-07-16: v1.3 Phase3（ジャンルグラフ）。mysteryクラスタから見て、
    literary・sfへそれぞれ何件のBridge Worksでつながっているかを正しく
    集計し、CLUSTER_TO_GENREでジャンル名に変換して返すことを確認する。"""
    _seed_fixture(monkeypatch)
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_A, "蔵書内の橋渡し作品A", "著者Y", "テスト出版社", "その他", "その他"))
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_B, "蔵書内の橋渡し作品B", "著者Z", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        result = plam_module.get_connected_genres("mystery")
        by_genre = {r["genre"]: r for r in result}
        assert by_genre["文芸小説"]["count"] == 1
        assert by_genre["ファンタジー・SF"]["count"] == 1
        assert by_genre["文芸小説"]["sample_works"][0]["title"] == "蔵書内の橋渡し作品A"
    finally:
        con = get_con()
        execute(con, "DELETE FROM genre_books WHERE isbn IN (?,?)", (_TEST_ISBN_A, _TEST_ISBN_B))
        con.commit()
        con.close()


def test_get_connected_genres_excludes_unmapped_clusters(monkeypatch):
    """CLUSTER_TO_GENREに存在しないクラスタ（例: horror）への接続は、
    ジャンルボタンが無いため表示対象から除外されることを確認する。"""
    fixtures = {
        "bridge_works.csv": [
            {"work_id": "BH1", "title": "蔵書内のホラー橋渡し作品", "author": "著者H",
             "bridge_type": "cross_cluster", "clusters": "mystery horror", "award_count": "1"},
        ],
    }
    monkeypatch.setattr(plam_module, "_read", lambda filename: fixtures.get(filename, []))
    con = get_con()
    execute(con, "INSERT OR REPLACE INTO genre_books (isbn, title, author, publisher, genre, format) "
            "VALUES (?,?,?,?,?,?)",
            (_TEST_ISBN_A, "蔵書内のホラー橋渡し作品", "著者H", "テスト出版社", "その他", "その他"))
    con.commit()
    con.close()
    try:
        result = plam_module.get_connected_genres("mystery")
        assert result == []
    finally:
        con = get_con()
        execute(con, "DELETE FROM genre_books WHERE isbn=?", (_TEST_ISBN_A,))
        con.commit()
        con.close()

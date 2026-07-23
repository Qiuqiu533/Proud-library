"""
v1.4 Phase2（利用状況計測基盤）の回帰テスト。
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("BOARD_PASSWORD", "test-board-pw")
os.environ.setdefault("RESIDENT_PASSWORD", "test-resident-pw")

from database import get_con, execute, fetchall
from services.analytics import log_event, VALID_EVENT_TYPES
import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def _cleanup():
    con = get_con()
    execute(con, "DELETE FROM usage_events WHERE session_id=?", ("test-session-001",))
    con.commit()
    con.close()


def test_log_event_persists_valid_event():
    try:
        ok = log_event("detail_view", book_isbn="9784000000000", genre="文芸小説",
                        plam_cluster="literary", source="search", session_id="test-session-001")
        assert ok is True

        con = get_con()
        rows = fetchall(con, "SELECT * FROM usage_events WHERE session_id=?", ("test-session-001",))
        con.close()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "detail_view"
        assert rows[0]["book_isbn"] == "9784000000000"
        assert rows[0]["plam_cluster"] == "literary"
    finally:
        _cleanup()


def test_log_event_rejects_invalid_event_type():
    ok = log_event("not_a_real_event_type", session_id="test-session-001")
    assert ok is False
    con = get_con()
    rows = fetchall(con, "SELECT * FROM usage_events WHERE session_id=?", ("test-session-001",))
    con.close()
    assert len(rows) == 0


def test_all_valid_event_types_are_documented():
    """Phase2で計測対象とした6種類のイベントが揃っていることを確認する。"""
    assert VALID_EVENT_TYPES == {
        "detail_view", "search", "search_zero",
        "recommendation_click", "bridge_click", "genre_view",
    }


def test_api_track_endpoint_persists_event(client):
    try:
        res = client.post("/api/track", json={
            "event_type": "bridge_click", "book_isbn": "9784000000001",
            "source": "genre_page", "session_id": "test-session-001",
        })
        assert res.status_code == 200
        assert res.get_json()["ok"] is True

        con = get_con()
        rows = fetchall(con, "SELECT * FROM usage_events WHERE session_id=?", ("test-session-001",))
        con.close()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "bridge_click"
    finally:
        _cleanup()


def test_api_track_endpoint_ignores_unknown_event_type(client):
    res = client.post("/api/track", json={"event_type": "hack_attempt", "session_id": "test-session-001"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is False
    con = get_con()
    rows = fetchall(con, "SELECT * FROM usage_events WHERE session_id=?", ("test-session-001",))
    con.close()
    assert len(rows) == 0


def _cleanup_usage_stats_events():
    con = get_con()
    execute(con, "DELETE FROM usage_events WHERE session_id=?", ("test-session-usagestats",))
    con.commit()
    con.close()


def test_usage_stats_requires_board_password(client):
    res = client.get("/api/admin/usage-stats")
    assert res.status_code == 401


def test_usage_stats_excludes_deploy_verify_but_includes_null_and_other_source(client):
    try:
        log_event("detail_view", book_isbn="9784000000010", source="deploy_verify", session_id="test-session-usagestats")
        log_event("detail_view", book_isbn="9784000000011", session_id="test-session-usagestats")  # source=NULL
        log_event("detail_view", book_isbn="9784000000012", source="home_popular", session_id="test-session-usagestats")

        res = client.get("/api/admin/usage-stats?period=all", headers={"X-Password": "test-board-pw"})
        assert res.status_code == 200
        data = res.get_json()

        isbns = {b["isbn"] for b in data["top_books"]}
        assert "9784000000010" not in isbns
        assert "9784000000011" in isbns
        assert "9784000000012" in isbns
    finally:
        _cleanup_usage_stats_events()


def test_usage_stats_response_shape(client):
    res = client.get("/api/admin/usage-stats?period=7d", headers={"X-Password": "test-board-pw"})
    assert res.status_code == 200
    data = res.get_json()
    for key in ("type_counts", "daily_trend", "top_books", "top_genres",
                "search_total", "search_zero_rate", "detail_view_count",
                "recommendation_click_count", "bridge_click_count"):
        assert key in data

"""
主要APIエンドポイントの統合テスト。
DATABASE_URL 未設定時はインメモリSQLite で実行。
"""
import sys, os, json, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# テスト用にインメモリDBを強制使用
os.environ.setdefault("DATABASE_URL", "")

import app as flask_app

@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


# ─── 公開エンドポイント ────────────────────────────────────────────────────

def test_index(client):
    res = client.get("/")
    assert res.status_code == 200

def test_ping(client):
    res = client.get("/ping")
    assert res.status_code == 200

def test_books_by_genre(client):
    res = client.get("/api/books/by-genre")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "books" in data
    assert "total" in data

def test_books_by_genre_keyword(client):
    res = client.get("/api/books/by-genre?keyword=テスト")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "books" in data

def test_books_popular(client):
    res = client.get("/api/books/popular")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert isinstance(data, list)

def test_stats(client):
    res = client.get("/api/stats")
    assert res.status_code == 200

def test_new_arrivals(client):
    res = client.get("/api/new-arrivals")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert isinstance(data, list)

def test_collections(client):
    res = client.get("/api/collections")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert isinstance(data, list)

def test_announcements(client):
    res = client.get("/api/announcements")
    assert res.status_code == 200

def test_award_books(client):
    res = client.get("/api/award-books")
    assert res.status_code == 200


# ─── 認証エンドポイント ────────────────────────────────────────────────────

def test_register_missing_fields(client):
    res = client.post("/api/user/register",
                      json={"room": "", "password": "", "email": ""})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "error" in data

def test_register_short_password(client):
    res = client.post("/api/user/register",
                      json={"room": "1-101", "password": "short1", "email": "a@b.com"})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "8文字以上" in data["error"]

def test_register_invalid_room(client):
    res = client.post("/api/user/register",
                      json={"room": "invalid", "password": "password123", "email": "a@b.com"})
    assert res.status_code == 400

def test_login_nonexistent_user(client):
    res = client.post("/api/user/login",
                      json={"room": "9-999", "password": "password123"})
    assert res.status_code in (400, 401)

def test_admin_login_wrong_password(client):
    res = client.post("/api/admin/login",
                      json={"code": "TEST", "password": "wrongpassword"})
    assert res.status_code == 401


# ─── 評価エンドポイント ────────────────────────────────────────────────────

def test_rate_invalid_score(client):
    res = client.post("/api/rate",
                      json={"isbn": "9784000000000", "score": 0})
    assert res.status_code == 400

def test_rate_score_out_of_range(client):
    res = client.post("/api/rate",
                      json={"isbn": "9784000000000", "score": 6})
    assert res.status_code == 400

def test_rate_missing_isbn(client):
    res = client.post("/api/rate", json={"score": 3})
    assert res.status_code == 400

def test_delete_review_no_auth(client):
    """room なし削除は認証エラー"""
    res = client.delete("/api/rate/review",
                        json={"isbn": "9784000000000", "review_id": "xxx"})
    assert res.status_code in (400, 401)


# ─── リクエスト・コミュニティ ──────────────────────────────────────────────

def test_requests_list(client):
    res = client.get("/api/requests")
    assert res.status_code == 200

def test_issues_list(client):
    res = client.get("/api/issues")
    assert res.status_code == 200

def test_calendar_list(client):
    res = client.get("/api/calendar")
    assert res.status_code == 200

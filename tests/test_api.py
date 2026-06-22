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

def test_lib_schedule_list(client):
    res = client.get("/api/lib-schedule")
    assert res.status_code == 200
    assert isinstance(json.loads(res.data), list)

def test_announcements_list(client):
    res = client.get("/api/announcements")
    assert res.status_code == 200

# ─── 書き込み系: 認証なし → 401 ───────────────────────────────────────────

def test_post_request_no_auth(client):
    """未認証（room/password なし）のリクエスト投稿は 401"""
    res = client.post("/api/requests", json={"title": "テスト本"})
    assert res.status_code == 401

def test_post_request_wrong_password(client):
    """存在しない部屋番号でのリクエスト投稿は 401"""
    res = client.post("/api/requests",
                      json={"title": "テスト本", "room": "9-999", "password": "wrongpass"})
    assert res.status_code == 401

def test_post_issue_wrong_auth(client):
    """間違った管理者パスワードの課題投稿は 401"""
    res = client.post("/api/issues",
                      json={"title": "テスト課題", "password": "wrong_password_xyz"})
    assert res.status_code == 401

def test_post_calendar_wrong_auth(client):
    """間違った管理者パスワードのカレンダー投稿は 401"""
    res = client.post("/api/calendar",
                      json={"title": "テストイベント", "event_date": "2026-07-01",
                            "password": "wrong_password_xyz"})
    assert res.status_code == 401

def test_post_lib_schedule_wrong_auth(client):
    """間違った管理者パスワードの休館日登録は 401"""
    res = client.post("/api/lib-schedule",
                      json={"title": "臨時休館", "event_date": "2026-07-01",
                            "type": "closed", "password": "wrong_password_xyz"})
    assert res.status_code == 401

def test_delete_issue_wrong_auth(client):
    """間違ったパスワードの課題削除は 401"""
    res = client.delete("/api/issues/1", json={"password": "wrong_password_xyz"})
    assert res.status_code == 401

def test_patch_request_wrong_auth(client):
    """間違ったパスワードのリクエストステータス変更は 401"""
    res = client.patch("/api/requests/1",
                       json={"status": "done", "password": "wrong_password_xyz"})
    assert res.status_code == 401

# ─── 評価・コメント 書き込み ──────────────────────────────────────────────

def test_delete_review_wrong_room(client):
    """他人のコメント削除（不正な review_id）は 400 または 404"""
    res = client.delete("/api/rate/review",
                        json={"isbn": "9784000000000", "room": "1-101",
                              "password": "dummypass", "review_id": "nonexistent"})
    assert res.status_code in (400, 401, 404)

# ─── ユーザー: パスワード変更 ─────────────────────────────────────────────

def test_change_password_no_auth(client):
    """認証なしのパスワード変更は 400 または 401"""
    res = client.post("/api/user/change-password",
                      json={"room": "9-999", "old_password": "pass", "new_password": "short"})
    assert res.status_code in (400, 401)

def test_change_password_short(client):
    """8文字未満の新パスワードは 400"""
    res = client.post("/api/user/change-password",
                      json={"room": "9-999", "old_password": "oldpass123", "new_password": "abc"})
    assert res.status_code == 400

# ─── ウィッシュリスト ─────────────────────────────────────────────────────

def test_wishlist_get_no_auth(client):
    """パスワードなしのGETは 401"""
    res = client.get("/api/wishlist?room=1-101")
    assert res.status_code == 401

def test_wishlist_get_wrong_password(client):
    """存在しない部屋のGETは 401"""
    res = client.get("/api/wishlist?room=9-999&password=wrongpass")
    assert res.status_code == 401

def test_wishlist_post_no_auth(client):
    """認証なしのPOSTは 401"""
    res = client.post("/api/wishlist",
                      json={"room": "9-999", "password": "nopass", "isbn": "9784000000000"})
    assert res.status_code == 401

def test_wishlist_delete_no_auth(client):
    """認証なしのDELETEは 401"""
    res = client.delete("/api/wishlist",
                        json={"room": "9-999", "password": "nopass", "isbn": "9784000000000"})
    assert res.status_code == 401

def test_wishlist_get_no_room(client):
    """roomなしのGETは 401"""
    res = client.get("/api/wishlist")
    assert res.status_code == 401

def test_ops_stats_no_auth(client):
    """認証なしの運営統計は 401"""
    res = client.get("/api/admin/ops-stats")
    assert res.status_code == 401


def test_ops_stats_with_auth(client):
    """正しい認証で運営統計が取得できる（テスト環境のboard_passwordは空文字）"""
    res = client.get("/api/admin/ops-stats", headers={"X-Password": ""})
    assert res.status_code == 200
    data = res.get_json()
    assert "loaned" in data
    assert "genres" in data
    assert "members" in data


def test_wishlist_summary_no_auth(client):
    """認証なしのウィッシュリスト集計は 401"""
    res = client.get("/api/admin/wishlist-summary")
    assert res.status_code == 401


def test_wishlist_summary_with_auth(client):
    """正しい認証でウィッシュリスト集計が取得できる（テスト環境のboard_passwordは空文字）"""
    res = client.get("/api/admin/wishlist-summary", headers={"X-Password": ""})
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_award_books_list(client):
    """受賞作一覧が取得できる"""
    res = client.get("/api/award-books")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_award_books_awards_list(client):
    """受賞作フィルター用の賞一覧が取得できる"""
    res = client.get("/api/award-books/awards")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_award_books_post_wrong_auth(client):
    """誤ったパスワードでの受賞作登録は 403"""
    res = client.post("/api/award-books", json={
        "password": "wrongpass", "award": "直木賞", "award_no": 1,
        "award_year": 2020, "title": "テスト", "author": "著者"
    })
    assert res.status_code == 403

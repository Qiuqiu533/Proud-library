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


# ─── POST/PATCH/DELETE 正常系テスト ─────────────────────────────────────────

def test_wishlist_add_and_delete(client):
    """ウィッシュリスト追加→削除の正常系（テスト用ユーザーを作成して検証）"""
    # ユーザー登録
    reg = client.post("/api/user/register", json={"room": "1-101", "password": "testpass1", "email": "test101@example.com"})
    assert reg.status_code in (200, 409)  # 既存でも可

    # 追加
    add = client.post("/api/wishlist", json={"room": "1-101", "password": "testpass1", "isbn": "9784000000001"})
    assert add.status_code == 200
    assert add.get_json().get("ok")

    # GETで確認
    get_res = client.get("/api/wishlist?room=1-101", headers={"X-Password": "testpass1"})
    assert get_res.status_code == 200
    isbns = [i["isbn"] for i in get_res.get_json()]
    assert "9784000000001" in isbns

    # 削除
    delete = client.delete("/api/wishlist", json={"room": "1-101", "password": "testpass1", "isbn": "9784000000001"})
    assert delete.status_code == 200
    assert delete.get_json().get("ok")


def test_post_request_ok(client):
    """ログイン済みユーザーによるリクエスト投稿の正常系"""
    client.post("/api/user/register", json={"room": "1-102", "password": "testpass1", "email": "test102@example.com"})
    res = client.post("/api/requests", json={
        "title": "テスト本", "author": "著者名", "reason": "読みたい",
        "room": "1-102", "password": "testpass1", "type": "request"
    })
    assert res.status_code == 200
    assert res.get_json().get("ok")


def test_post_feedback_ok(client):
    """ログイン済みユーザーによるご要望投稿の正常系"""
    client.post("/api/user/register", json={"room": "1-103", "password": "testpass1", "email": "test103@example.com"})
    res = client.post("/api/requests", json={
        "title": "図書館の開館時間を延ばしてほしい", "reason": "希望",
        "room": "1-103", "password": "testpass1", "type": "feedback"
    })
    assert res.status_code == 200
    assert res.get_json().get("ok")


def test_patch_request_status_ok(client):
    """管理者によるリクエストステータス変更の正常系"""
    # リクエストを取得して最初のIDに対してPATCH
    reqs = client.get("/api/requests").get_json()
    if not reqs:
        return  # データなしはスキップ
    req_id = reqs[0]["id"]
    res = client.patch(f"/api/requests/{req_id}", json={"status": "approved"},
                       headers={"X-Password": ""})
    assert res.status_code == 200
    assert res.get_json().get("ok")


def test_user_login_ok(client):
    """ユーザー登録→ログインの正常系"""
    client.post("/api/user/register", json={"room": "1-104", "password": "testpass1", "email": "test104@example.com"})
    res = client.post("/api/user/login", json={"room": "1-104", "password": "testpass1", "email": "test104@example.com"})
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("ok")
    assert data.get("room") == "1-104"


def test_user_login_wrong_password(client):
    """ログイン失敗（パスワード誤り）は 401"""
    client.post("/api/user/register", json={"room": "1-105", "password": "testpass1", "email": "test105@example.com"})
    res = client.post("/api/user/login", json={"room": "1-105", "password": "wrongpass"})
    assert res.status_code == 401


def test_wishlist_notify_toggle(client):
    """ウィッシュリスト通知ON/OFF切り替えの正常系"""
    client.post("/api/user/register", json={"room": "1-106", "password": "testpass1", "email": "test106@example.com"})
    client.post("/api/wishlist", json={"room": "1-106", "password": "testpass1", "isbn": "9784101092058"})
    # 通知OFFに変更
    res = client.patch("/api/wishlist/notify",
                       json={"room": "1-106", "password": "testpass1",
                             "isbn": "9784101092058", "notify": False})
    assert res.status_code == 200
    assert res.get_json().get("notify") is False
    # 通知ONに戻す
    res = client.patch("/api/wishlist/notify",
                       json={"room": "1-106", "password": "testpass1",
                             "isbn": "9784101092058", "notify": True})
    assert res.status_code == 200
    assert res.get_json().get("notify") is True


def test_wishlist_notify_wrong_auth(client):
    """認証失敗時は 401"""
    res = client.patch("/api/wishlist/notify",
                       json={"room": "1-106", "password": "wrongpass",
                             "isbn": "9784101092058", "notify": False})
    assert res.status_code == 401


def test_wishlist_includes_notify_field(client):
    """GET /api/wishlist のレスポンスに notify フィールドが含まれる"""
    client.post("/api/user/register", json={"room": "1-107", "password": "testpass1", "email": "test107@example.com"})
    client.post("/api/wishlist", json={"room": "1-107", "password": "testpass1", "isbn": "9784101092058"})
    res = client.get("/api/wishlist?room=1-107", headers={"X-Password": "testpass1"})
    assert res.status_code == 200
    data = res.get_json()
    assert len(data) > 0
    assert "notify" in data[0]


# ===== 招待コード =====

def test_invite_codes_list_no_auth(client):
    """未認証では招待コード一覧は 401"""
    res = client.get("/api/admin/invite-codes", headers={"X-Password": "wrong"})
    assert res.status_code == 401


def test_invite_codes_issue_and_list(client):
    """招待コード発行→一覧に表示される"""
    res = client.post("/api/admin/invite-codes",
                      json={"count": 3, "note": "テスト"},
                      headers={"X-Password": ""})
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("ok")
    assert len(data.get("codes", [])) == 3

    res2 = client.get("/api/admin/invite-codes", headers={"X-Password": ""})
    assert res2.status_code == 200
    codes_in_db = [r["code"] for r in res2.get_json()]
    for c in data["codes"]:
        assert c in codes_in_db


def test_invite_validate_valid(client):
    """有効な招待コードの検証は valid=True"""
    issue = client.post("/api/admin/invite-codes",
                        json={"count": 1},
                        headers={"X-Password": ""})
    code = issue.get_json()["codes"][0]
    res = client.post("/api/invite/validate", json={"code": code})
    assert res.status_code == 200
    assert res.get_json().get("valid") is True


def test_invite_validate_invalid(client):
    """存在しないコードは valid=False"""
    res = client.post("/api/invite/validate", json={"code": "XXXXXXXX"})
    assert res.status_code == 400
    assert res.get_json().get("valid") is False


def test_invite_delete_unused(client):
    """未使用コードの削除"""
    issue = client.post("/api/admin/invite-codes",
                        json={"count": 1},
                        headers={"X-Password": ""})
    code_id_list = client.get("/api/admin/invite-codes", headers={"X-Password": ""}).get_json()
    issued_code = issue.get_json()["codes"][0]
    target = next((r for r in code_id_list if r["code"] == issued_code), None)
    assert target is not None
    res = client.delete(f"/api/admin/invite-codes/{target['id']}",
                        headers={"X-Password": ""})
    assert res.status_code == 200
    assert res.get_json().get("ok")


# ── イベント申込テスト ──────────────────────────────────────────────────────

def _register_user(client, room="1-101", password="pass1234", email="test@example.com"):
    client.post("/api/user/register", json={"room": room, "password": password, "email": email})


def _get_event_id(client, title):
    events = client.get("/api/events").get_json()
    ev = next((e for e in events if e["title"] == title), None)
    assert ev is not None, f"イベント '{title}' が見つかりません"
    return ev["id"]


def test_events_list_public(client):
    """公開イベント一覧が取得できる"""
    res = client.get("/api/events")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_admin_create_and_list_event(client):
    """管理者がイベント作成→一覧取得"""
    res = client.post("/api/admin/events",
                      json={"title": "読書会テスト", "event_date": "2026-08-01",
                            "capacity": 10, "status": "open"},
                      headers={"X-Password": ""})
    assert res.status_code == 200
    assert res.get_json()["ok"]

    events = client.get("/api/events").get_json()
    assert any(e["title"] == "読書会テスト" for e in events)


def test_event_entry_and_cancel(client):
    """住民がイベント申込→キャンセル"""
    _register_user(client, room="1-201", password="test5678", email="u201@test.com")
    client.post("/api/admin/events",
                json={"title": "映画上映会テスト", "event_date": "2026-09-01",
                      "capacity": 5, "status": "open"},
                headers={"X-Password": ""})
    event_id = _get_event_id(client, "映画上映会テスト")

    res = client.post(f"/api/events/{event_id}/entry",
                      json={"room": "1-201", "password": "test5678", "name": "テスト住民"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "confirmed"

    events = client.get("/api/events").get_json()
    ev = next(e for e in events if e["id"] == event_id)
    assert ev["confirmed"] == 1

    res2 = client.delete(f"/api/events/{event_id}/entry",
                         json={"room": "1-201", "password": "test5678"})
    assert res2.status_code == 200


def test_event_waitlist(client):
    """定員超でキャンセル待ちに登録"""
    _register_user(client, room="1-301", password="test5678", email="u301@test.com")
    _register_user(client, room="1-302", password="test5678", email="u302@test.com")
    client.post("/api/admin/events",
                json={"title": "定員テスト", "event_date": "2026-10-01",
                      "capacity": 1, "status": "open"},
                headers={"X-Password": ""})
    event_id = _get_event_id(client, "定員テスト")

    r1 = client.post(f"/api/events/{event_id}/entry",
                     json={"room": "1-301", "password": "test5678"})
    assert r1.get_json()["status"] == "confirmed"

    r2 = client.post(f"/api/events/{event_id}/entry",
                     json={"room": "1-302", "password": "test5678"})
    assert r2.get_json()["status"] == "waitlist"

    events = client.get("/api/events").get_json()
    ev = next(e for e in events if e["id"] == event_id)
    assert ev["confirmed"] == 1 and ev["waitlist"] == 1


def test_event_waitlist_promotion(client):
    """確定者キャンセル→キャンセル待ちが繰り上がる"""
    _register_user(client, room="1-401", password="test5678", email="u401@test.com")
    _register_user(client, room="1-402", password="test5678", email="u402@test.com")
    client.post("/api/admin/events",
                json={"title": "繰り上げテスト", "event_date": "2026-11-01",
                      "capacity": 1, "status": "open"},
                headers={"X-Password": ""})
    event_id = _get_event_id(client, "繰り上げテスト")

    client.post(f"/api/events/{event_id}/entry", json={"room": "1-401", "password": "test5678"})
    client.post(f"/api/events/{event_id}/entry", json={"room": "1-402", "password": "test5678"})

    client.delete(f"/api/events/{event_id}/entry", json={"room": "1-401", "password": "test5678"})

    entries = client.get(f"/api/admin/events/{event_id}/entries",
                         headers={"X-Password": ""}).get_json()
    room402 = next(e for e in entries if e["room"] == "1-402")
    assert not room402["is_waitlist"]


def test_event_duplicate_entry(client):
    """同じ部屋番号で二重申込は409"""
    _register_user(client, room="1-501", password="test5678", email="u501@test.com")
    client.post("/api/admin/events",
                json={"title": "重複テスト", "event_date": "2026-12-01",
                      "capacity": 10, "status": "open"},
                headers={"X-Password": ""})
    event_id = _get_event_id(client, "重複テスト")

    client.post(f"/api/events/{event_id}/entry", json={"room": "1-501", "password": "test5678"})
    r2 = client.post(f"/api/events/{event_id}/entry", json={"room": "1-501", "password": "test5678"})
    assert r2.status_code == 409


def test_event_unauth_entry(client):
    """未認証の申込は401"""
    client.post("/api/admin/events",
                json={"title": "認証テスト", "event_date": "2026-12-15",
                      "capacity": 5, "status": "open"},
                headers={"X-Password": ""})
    event_id = _get_event_id(client, "認証テスト")
    res = client.post(f"/api/events/{event_id}/entry",
                      json={"room": "9999", "password": "wrong"})
    assert res.status_code == 401


def test_admin_delete_event(client):
    """管理者がイベント削除"""
    client.post("/api/admin/events",
                json={"title": "削除テスト固有", "event_date": "2026-12-31",
                      "capacity": 0, "status": "open"},
                headers={"X-Password": ""})
    event_id = _get_event_id(client, "削除テスト固有")
    res = client.delete(f"/api/admin/events/{event_id}", headers={"X-Password": ""})
    assert res.status_code == 200
    assert res.get_json()["ok"]
    events = client.get("/api/events").get_json()
    assert not any(e["title"] == "削除テスト固有" for e in events)

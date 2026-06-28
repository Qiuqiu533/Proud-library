"""
主要利用シナリオのE2Eテスト（Flask test clientによるAPIレベル検証）。

シナリオ:
 S1: 住民登録 → ログイン → 蔵書検索 → 詳細取得
 S2: オートコンプリート候補取得
 S3: 読みたいリスト追加・削除
 S4: 評価投稿（住民認証）
 S5: イベント一覧取得 → .icsダウンロード
 S6: 管理者ログイン → 新着図書登録 → 運営統計取得
 S7: 新着図書API → 書影URLがNDLまたはlibrarylifeドメインか確認
"""
import sys, os, json, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ADMIN_PASSWORD",    "test-admin-pw")
os.environ.setdefault("BOARD_PASSWORD",    "test-board-pw")
os.environ.setdefault("RESIDENT_PASSWORD", "test-resident-pw")

import app as flask_app

BOARD_PW = "test-board-pw"
RESIDENT_PW = "test-resident-pw"


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


@pytest.fixture
def registered_user(client):
    """テスト用住民アカウントを登録してroomを返す。毎回クリーンな状態にする。"""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from database import get_con, execute
    room = "5-0533"
    con = get_con()
    execute(con, "DELETE FROM user_accounts WHERE room=?", (room,))
    con.commit(); con.close()
    client.post("/api/user/register", json={
        "room": room, "password": RESIDENT_PW,
        "email": "e2e@test.example"
    })
    return room


# ─── S1: 蔵書検索シナリオ ────────────────────────────────────────────────

def test_s1_search_books(client):
    """蔵書検索APIが正常なJSONを返す。"""
    res = client.get("/api/books?keyword=&page=1")
    assert res.status_code == 200
    data = res.get_json()
    assert "books" in data
    assert "total" in data


def test_s1_search_with_keyword(client):
    """キーワード検索でbooksリストが返る。"""
    res = client.get("/api/books?keyword=テスト&page=1")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data["books"], list)


# ─── S2: オートコンプリート ───────────────────────────────────────────────

def test_s2_autocomplete_empty(client):
    """クエリなしで空リストが返る。"""
    res = client.get("/api/books/suggest?q=")
    assert res.status_code == 200
    assert res.get_json() == []


def test_s2_autocomplete_query(client):
    """クエリありでリストが返る（件数は0以上）。"""
    res = client.get("/api/books/suggest?q=東野")
    assert res.status_code == 200
    result = res.get_json()
    assert isinstance(result, list)
    for item in result:
        assert "isbn" in item
        assert "title" in item
        assert "author" in item


# ─── S3: 読みたいリスト ───────────────────────────────────────────────────

def test_s3_wishlist_crud(client, registered_user):
    """読みたいリスト追加・取得・削除の一連フロー。"""
    room = registered_user
    isbn = "9784000000001"

    # 追加
    res = client.post("/api/wishlist", json={
        "isbn": isbn, "room": room, "password": RESIDENT_PW
    })
    assert res.status_code in (200, 201)

    # 一覧取得
    res = client.get(f"/api/wishlist?room={room}", headers={"X-Password": RESIDENT_PW})
    assert res.status_code == 200
    items = res.get_json()
    assert any(w["isbn"] == isbn for w in items)

    # 削除
    res = client.delete("/api/wishlist", json={
        "isbn": isbn, "room": room, "password": RESIDENT_PW
    })
    assert res.status_code == 200


# ─── S4: 評価投稿 ─────────────────────────────────────────────────────────

def test_s4_rate_book(client, registered_user):
    """住民認証で評価を投稿し、評価が取得できる。"""
    room = registered_user
    isbn = "9784000000002"

    res = client.post("/api/rate", json={
        "isbn": isbn, "score": 4, "review": "面白かった",
        "room": room, "password": RESIDENT_PW
    })
    assert res.status_code == 200

    res = client.get(f"/api/book/{isbn}?room={room}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["rating"]["votes"] >= 1


# ─── S5: イベント + .icsダウンロード ─────────────────────────────────────

def test_s5_events_list(client):
    """イベント一覧が正常に返る。"""
    res = client.get("/api/events")
    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_s5_ics_not_found(client):
    """存在しないイベントの.icsは404を返す。"""
    res = client.get("/api/events/99999/ics")
    assert res.status_code == 404


def test_s5_ics_download(client):
    """イベントを作成して.icsが取得できる。"""
    # イベント作成（管理者）
    res = client.post("/api/admin/events",
        headers={"X-Password": BOARD_PW},
        json={
        "title": "読書会テスト",
        "description": "テスト用イベント",
        "event_date": "2026-09-01",
        "event_time": "14:00",
        "location": "集会室",
        "capacity": 10,
        "entry_deadline": "2026-08-25",
        "status": "open"
    })
    assert res.status_code == 200

    # イベント一覧から作成したイベントのIDを取得
    list_res = client.get("/api/admin/events", headers={"X-Password": BOARD_PW})
    events = list_res.get_json()
    event_id = next((e["id"] for e in events if e.get("title") == "読書会テスト"), None)
    assert event_id, f"作成したイベントが見つかりません: {events}"

    # .icsダウンロード
    res = client.get(f"/api/events/{event_id}/ics")
    assert res.status_code == 200
    assert "text/calendar" in res.content_type
    body = res.data.decode()
    assert "BEGIN:VCALENDAR" in body
    assert "読書会テスト" in body
    assert "DTSTART:" in body


# ─── S6: 管理者シナリオ ───────────────────────────────────────────────────

def test_s6_admin_new_arrival(client):
    """新着図書を登録して一覧に現れる。"""
    res = client.post("/api/new-arrivals", json={
        "password": BOARD_PW,
        "isbn": "9784000099001",
        "title": "テスト本",
        "author": "テスト著者",
        "publisher": "テスト出版",
        "arrived_at": "2026-06-28"
    })
    assert res.status_code == 200

    res = client.get("/api/books/new")
    assert res.status_code == 200
    data = res.get_json()
    isbns = [b["isbn"] for b in data["books"]]
    assert "9784000099001" in isbns


def test_s6_admin_reset_user_password(client, registered_user):
    """管理者が住民パスワードをリセットできる。"""
    room = registered_user
    res = client.post("/api/admin/reset-user-password",
        headers={"X-Password": BOARD_PW},
        json={"room": room, "new_password": "NewPass123"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    # 新パスワードでログインできる
    res2 = client.post("/api/user/login", json={"room": room, "password": "NewPass123"})
    assert res2.status_code == 200

    # 存在しない部屋番号は404
    res3 = client.post("/api/admin/reset-user-password",
        headers={"X-Password": BOARD_PW},
        json={"room": "9-999", "new_password": "NewPass123"})
    assert res3.status_code == 404

    # 認証なしは401
    res4 = client.post("/api/admin/reset-user-password",
        json={"room": room, "new_password": "NewPass123"})
    assert res4.status_code == 401


def test_s6_ops_stats(client):
    """運営統計が正常なデータ構造を返す。"""
    res = client.get("/api/admin/ops-stats", headers={"X-Password": BOARD_PW})
    assert res.status_code == 200
    d = res.get_json()
    for key in ("members", "loaned", "total_books", "top_rated", "genres",
                "top_authors", "dead_stock"):
        assert key in d, f"キー '{key}' がレスポンスにない"


# ─── S7: 書影URLドメイン確認 ─────────────────────────────────────────────

ALLOWED_COVER_DOMAINS = (
    "ndlsearch.ndl.go.jp",
    "www.librarylife.net",
    "librarylife.net",
    "images-na.ssl-images-amazon.com",
    "m.media-amazon.com",
    "covers.openlibrary.org",
    "books.google.com",
    "books.googleusercontent.com",
    "lh3.googleusercontent.com",
)

def test_s7_new_arrival_cover_domains(client):
    """新着図書の書影URLが許可ドメインのものか、または空である。"""
    res = client.get("/api/books/new")
    assert res.status_code == 200
    books = res.get_json().get("books", [])
    for b in books[:10]:
        cover = b.get("cover", "")
        if cover:
            assert any(d in cover for d in ALLOWED_COVER_DOMAINS), \
                f"許可外ドメインの書影URL: {cover}"

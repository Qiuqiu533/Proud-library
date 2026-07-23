"""
緊急対応フォローアップ（2026-07-21）: auto_cleanup_images() が、画像を伴う投稿の
DB保存成功後にのみ呼ばれ、画像なし投稿では呼ばれないことの回帰テスト。
起動時フォールバックや時間ベースの間隔ゲートは意図的に設けていない
（判定自体がget_setting()経由でDB接続を伴い、Neonの起動時間を増やすため）。
"""
import sys, os, pytest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("BOARD_PASSWORD", "test-board-pw")
os.environ.setdefault("RESIDENT_PASSWORD", "test-resident-pw")

from database import USE_PG
import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_auto_cleanup_images_is_noop_without_pg():
    """SQLite環境（USE_PG=False）では即returnし、DB接続を試みないことを確認する。"""
    from services.utils import auto_cleanup_images
    auto_cleanup_images()


def test_announcement_post_without_image_does_not_call_cleanup(client):
    with patch("routes.announcements.auto_cleanup_images") as mock_cleanup:
        res = client.post("/api/announcements", json={
            "title": "テストお知らせ", "body": "本文", "category": "お知らせ",
        }, headers={"X-Password": "test-board-pw"})
        assert res.status_code == 200
        mock_cleanup.assert_not_called()


def test_announcement_post_with_image_calls_cleanup(client):
    with patch("routes.announcements.auto_cleanup_images") as mock_cleanup:
        res = client.post("/api/announcements", json={
            "title": "画像付きお知らせ", "body": "本文", "category": "お知らせ",
            "images": ["data:image/png;base64,AAAA"],
        }, headers={"X-Password": "test-board-pw"})
        assert res.status_code == 200
        mock_cleanup.assert_called_once()


def test_staff_chat_post_without_image_does_not_call_cleanup(client):
    with patch("routes.admin.auto_cleanup_images") as mock_cleanup:
        res = client.post("/api/staff_chat", json={
            "password": "test-board-pw", "sender": "テスト", "message": "こんにちは",
        })
        assert res.status_code == 200
        mock_cleanup.assert_not_called()


def test_staff_chat_post_with_image_calls_cleanup(client):
    with patch("routes.admin.auto_cleanup_images") as mock_cleanup:
        res = client.post("/api/staff_chat", json={
            "password": "test-board-pw", "sender": "テスト", "message": "",
            "image_data": "data:image/png;base64,AAAA",
        })
        assert res.status_code == 200
        mock_cleanup.assert_called_once()


def test_announcement_post_unauthorized_does_not_call_cleanup(client):
    """認証失敗（DB保存されない）場合はcleanupが呼ばれないことを確認する。"""
    with patch("routes.announcements.auto_cleanup_images") as mock_cleanup:
        res = client.post("/api/announcements", json={
            "title": "不正投稿", "body": "本文",
            "images": ["data:image/png;base64,AAAA"],
        }, headers={"X-Password": "wrong-password"})
        assert res.status_code == 401
        mock_cleanup.assert_not_called()

"""
緊急対応（2026-07-21）: Neonの無料枠コンピュート時間を使い切った障害の再発防止テスト。
外形監視エンドポイント /ping は、GET・HEADいずれの場合もDBへ一切接続しないことを保証する。
（旧実装は/pingのたびにauto_cleanup_images()を呼び、外部監視の高頻度アクセスがNeonの
アイドルタイマーを継続的にリセットしてScale to Zeroを妨げていた。）
"""
import sys, os, pytest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("BOARD_PASSWORD", "test-board-pw")
os.environ.setdefault("RESIDENT_PASSWORD", "test-resident-pw")

import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_ping_get_does_not_touch_db(client):
    with patch("database.get_con") as mock_get_con:
        res = client.get("/ping")
        assert res.status_code == 200
        assert res.get_data(as_text=True) == "ok"
        mock_get_con.assert_not_called()


def test_ping_head_does_not_touch_db(client):
    with patch("database.get_con") as mock_get_con:
        res = client.head("/ping")
        assert res.status_code == 200
        mock_get_con.assert_not_called()


def test_ping_route_has_no_auto_cleanup_reference():
    """/pingの実装がauto_cleanup_imagesを呼び出していないことをソースレベルでも確認する。"""
    import inspect
    import routes.pages as pages
    src = inspect.getsource(pages.ping)
    assert "auto_cleanup_images" not in src

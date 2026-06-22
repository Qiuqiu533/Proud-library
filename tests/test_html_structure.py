"""
管理者パネルのHTML構造テスト。
btab-* パネルが同一階層（兄弟要素）に正しく配置されているかを検証する。
今回のような「btab-libschedule が btab-analytics の子要素になる」誤ネスト再発を防止する。
"""
import re
import os


TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "index.html")

EXPECTED_BTABS = [
    "btab-dashboard",
    "btab-adminnews",
    "btab-bookdesc",
    "btab-newarrival",
    "btab-issues",
    "btab-brequest",
    "btab-analytics",
    "btab-libschedule",
    "btab-calendar",
    "btab-staffchat",
    "btab-adminusers",
    "btab-settings",
    "btab-collections",
    "btab-awarddb",
    "btab-guide",
]


def _get_html():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def test_all_btab_panels_exist():
    """全 btab-* パネルが HTML 内に存在する"""
    html = _get_html()
    for btab in EXPECTED_BTABS:
        assert f'id="{btab}"' in html, f"パネル {btab} が HTML に存在しない"


def test_btab_panels_are_siblings():
    """btab-* パネルが同一階層（兄弟要素）になっているかを検証する。
    各パネルの開始位置が前のパネルの終了コメント以降にあることを確認する。
    特に btab-libschedule と btab-calendar が btab-analytics より後にあることを確認。"""
    html = _get_html()

    def pos(btab_id):
        m = re.search(rf'id="{btab_id}"', html)
        return m.start() if m else -1

    analytics_end = html.find("end btab-analytics")
    libschedule_start = pos("btab-libschedule")
    calendar_start = pos("btab-calendar")

    assert analytics_end > 0, "<!-- end btab-analytics --> コメントが見つからない"
    assert libschedule_start > analytics_end, (
        f"btab-libschedule ({libschedule_start}) が btab-analytics 終了 ({analytics_end}) より前にある — 誤ネストの疑い"
    )
    assert calendar_start > analytics_end, (
        f"btab-calendar ({calendar_start}) が btab-analytics 終了 ({analytics_end}) より前にある — 誤ネストの疑い"
    )


def test_btab_panels_in_order():
    """主要パネルが正しい順序で出現する"""
    html = _get_html()
    positions = {btab: html.find(f'id="{btab}"') for btab in EXPECTED_BTABS}
    ordered = sorted(positions.keys(), key=lambda k: positions[k])
    # analytics は libschedule・calendar より前にあるべき
    assert ordered.index("btab-analytics") < ordered.index("btab-libschedule")
    assert ordered.index("btab-analytics") < ordered.index("btab-calendar")

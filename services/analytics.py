"""
v1.4 Phase2: 利用状況計測基盤。

「作る→動く」から「作る→使われる→改善する」への転換のため、
最低限のイベントログ（本詳細表示・検索実行・検索0件・おすすめクリック・
Bridge Worksクリック・ジャンルページ閲覧）を記録する。

住民個人を特定しない匿名session_id（ブラウザのsessionStorageで生成）の
みを記録し、部屋番号・ログイン情報は一切保存しない。

集計・ダッシュボード（Phase2.5）は別途実装する。
"""
from __future__ import annotations
import logging

from database import get_con, execute, USE_PG

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = {
    "detail_view",           # 本詳細表示
    "search",                # 検索実行
    "search_zero",           # 検索0件
    "recommendation_click",  # おすすめクリック（人気作品・PLAM関連作品等）
    "bridge_click",          # Bridge Worksクリック
    "genre_view",            # ジャンルページ閲覧
}


def log_event(event_type: str, book_isbn: str = "", genre: str = "",
              plam_cluster: str = "", source: str = "", session_id: str = "") -> bool:
    """イベントを1件記録する。不正なevent_typeは無視する（例外は投げない）。"""
    if event_type not in VALID_EVENT_TYPES:
        return False
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        execute(
            con,
            f"""INSERT INTO usage_events (event_type, book_isbn, genre, plam_cluster, source, session_id)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph})""",
            (event_type, book_isbn or None, genre or None, plam_cluster or None,
             source or None, session_id or None),
        )
        con.commit()
        return True
    except Exception as e:
        logger.error("usage_events insert error: %s", e)
        try:
            con.rollback()
        except Exception:
            pass
        return False
    finally:
        con.close()

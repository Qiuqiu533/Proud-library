from flask import Blueprint, request, jsonify

from config import check_password
from database import get_con, fetchall, USE_PG
from services.analytics import log_event, VALID_EVENT_TYPES
from services.utils import rate_limit

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/api/track", methods=["POST"])
@rate_limit(limit=60, window=60)
def api_track():
    """v1.4 Phase2: 利用状況イベントを記録する（fire-and-forget、公開エンドポイント）。"""
    body = request.get_json(silent=True) or {}
    event_type = (body.get("event_type") or "").strip()
    if event_type not in VALID_EVENT_TYPES:
        return jsonify({"ok": False}), 200  # フロント側で無視できるよう200で返す
    log_event(
        event_type=event_type,
        book_isbn=(body.get("book_isbn") or "").strip()[:20],
        genre=(body.get("genre") or "").strip()[:50],
        plam_cluster=(body.get("plam_cluster") or "").strip()[:20],
        source=(body.get("source") or "").strip()[:100],
        session_id=(body.get("session_id") or "").strip()[:64],
    )
    return jsonify({"ok": True})


def _period_where(days, alias=""):
    """usage_eventsの期間フィルタ + 検証用イベント除外条件を返す。
    source='deploy_verify'（デプロイ確認用に送信したテストイベント）は集計対象から除外するが、
    source IS NULL（通常の未指定データ）は除外しない。
    """
    col = f"{alias}created_at" if alias else "created_at"
    src = f"{alias}source" if alias else "source"
    exclude = f"({src} IS NULL OR {src} != 'deploy_verify')"
    if days is None:
        return exclude
    date_clause = (
        f"{col} >= NOW() - INTERVAL '{days} days'" if USE_PG
        else f"{col} >= datetime('now', '-{days} days')"
    )
    return f"{date_clause} AND {exclude}"


@analytics_bp.route("/api/admin/usage-stats")
@rate_limit(limit=30, window=60)
def api_usage_stats():
    """v1.4 Phase2.5: 利用状況ダッシュボード集計（理事会/管理者限定）。"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401

    period = request.args.get("period", "7d")
    days = {"7d": 7, "30d": 30, "all": None}.get(period, 7)

    con = get_con()
    try:
        w = _period_where(days)
        wu = _period_where(days, alias="u.")

        type_counts_rows = fetchall(con, f"""
            SELECT event_type, COUNT(*) AS cnt FROM usage_events
            WHERE {w} GROUP BY event_type
        """)
        counts = {r["event_type"]: r["cnt"] for r in type_counts_rows}

        daily_trend = fetchall(con, f"""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt FROM usage_events
            WHERE {w} GROUP BY DATE(created_at) ORDER BY day
        """)

        top_books = fetchall(con, f"""
            SELECT u.book_isbn AS isbn, g.title AS title, COUNT(*) AS cnt
            FROM usage_events u
            LEFT JOIN genre_books g ON g.isbn = u.book_isbn
            WHERE u.book_isbn IS NOT NULL AND u.book_isbn != '' AND {wu}
            GROUP BY u.book_isbn, g.title
            ORDER BY cnt DESC LIMIT 10
        """)

        top_genres = fetchall(con, f"""
            SELECT genre, COUNT(*) AS cnt FROM usage_events
            WHERE event_type = 'genre_view' AND genre IS NOT NULL AND genre != '' AND {w}
            GROUP BY genre ORDER BY cnt DESC LIMIT 10
        """)

        search_cnt = counts.get("search", 0)
        search_zero_cnt = counts.get("search_zero", 0)
        search_total = search_cnt + search_zero_cnt
        zero_rate = round(search_zero_cnt / search_total * 100, 1) if search_total else 0

        return jsonify({
            "period": period,
            "type_counts": counts,
            "daily_trend": daily_trend,
            "top_books": top_books,
            "top_genres": top_genres,
            "search_total": search_total,
            "search_zero_count": search_zero_cnt,
            "search_zero_rate": zero_rate,
            "detail_view_count": counts.get("detail_view", 0),
            "recommendation_click_count": counts.get("recommendation_click", 0),
            "bridge_click_count": counts.get("bridge_click", 0),
        })
    finally:
        con.close()

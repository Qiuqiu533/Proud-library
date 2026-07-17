from flask import Blueprint, request, jsonify

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

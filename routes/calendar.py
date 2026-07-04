from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchone, fetchall
from services.utils import get_pw_from_request as _get_pw

calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.route("/api/calendar")
def api_calendar():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,event_date,body,minutes,sort_order,created_at FROM calendar_events ORDER BY sort_order ASC, event_date DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@calendar_bp.route("/api/calendar", methods=["POST"])
def api_post_calendar():
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    row = fetchone(con, "SELECT MIN(sort_order) as m FROM calendar_events")
    new_order = ((row["m"] or 0) - 1) if row else -1
    execute(con, "INSERT INTO calendar_events (title,event_date,body,minutes,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})


@calendar_bp.route("/api/calendar/reorder", methods=["POST"])
def api_reorder_calendar():
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    for item in body.get("order", []):
        execute(con, "UPDATE calendar_events SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})


@calendar_bp.route("/api/calendar/<int:ev_id>", methods=["PATCH"])
def api_update_calendar(ev_id):
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "UPDATE calendar_events SET title=?,event_date=?,body=?,minutes=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), ev_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@calendar_bp.route("/api/calendar/<int:ev_id>", methods=["DELETE"])
def api_delete_calendar(ev_id):
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM calendar_events WHERE id=?", (ev_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})

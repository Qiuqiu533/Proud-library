from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchall
from services.utils import get_pw_from_request as _get_pw

lib_schedule_bp = Blueprint("lib_schedule", __name__)


@lib_schedule_bp.route("/api/lib-schedule")
def api_lib_schedule():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,event_date,type,created_at FROM lib_schedule ORDER BY event_date ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@lib_schedule_bp.route("/api/lib-schedule", methods=["POST"])
def api_post_lib_schedule():
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "INSERT INTO lib_schedule (title,event_date,type) VALUES (?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""), body.get("type","event")))
    con.commit(); con.close()
    return jsonify({"ok": True})


@lib_schedule_bp.route("/api/lib-schedule/<int:sch_id>", methods=["PATCH"])
def api_update_lib_schedule(sch_id):
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "UPDATE lib_schedule SET title=?,event_date=?,type=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""), body.get("type","event"), sch_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@lib_schedule_bp.route("/api/lib-schedule/<int:sch_id>", methods=["DELETE"])
def api_delete_lib_schedule(sch_id):
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM lib_schedule WHERE id=?", (sch_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})

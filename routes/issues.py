from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchone, fetchall
from services.utils import get_pw_from_request as _get_pw

issues_bp = Blueprint("issues", __name__)


@issues_bp.route("/api/issues")
def api_issues():
    con = get_con()
    try:
        rows = fetchall(con, "SELECT id,title,body,priority,status,sort_order,created_at FROM issues ORDER BY sort_order ASC, id DESC")
        con.close()
        return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@issues_bp.route("/api/issues", methods=["POST"])
def api_post_issue():
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    row = fetchone(con, "SELECT MIN(sort_order) as m FROM issues")
    new_order = ((row["m"] or 0) - 1) if row else -1
    execute(con, "INSERT INTO issues (title,body,priority,status,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("body","").strip(),
         body.get("priority","中"), body.get("status","未対応"), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})


@issues_bp.route("/api/issues/reorder", methods=["POST"])
def api_reorder_issues():
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    for item in body.get("order", []):
        execute(con, "UPDATE issues SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})


@issues_bp.route("/api/issues/<int:issue_id>", methods=["PATCH"])
def api_update_issue(issue_id):
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if "title" in body:
        execute(con, "UPDATE issues SET title=?,body=?,priority=?,status=? WHERE id=?",
            (body["title"], body.get("body",""), body.get("priority","中"), body.get("status","未対応"), issue_id))
    elif "status" in body:
        execute(con, "UPDATE issues SET status=? WHERE id=?", (body["status"], issue_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@issues_bp.route("/api/issues/<int:issue_id>", methods=["DELETE"])
def api_delete_issue(issue_id):
    body = request.get_json()
    if not check_password(_get_pw(), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM issues WHERE id=?", (issue_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})

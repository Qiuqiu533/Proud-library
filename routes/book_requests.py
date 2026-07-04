from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchone, fetchall
from services.utils import rate_limit, get_pw_from_request as _get_pw
from services.audit import log_action

book_requests_bp = Blueprint("book_requests", __name__)


@book_requests_bp.route("/api/requests")
def api_requests():
    con = get_con()
    try:
        rows = fetchall(con, "SELECT id,title,author,reason,room,status,votes,created_at,type,reply FROM book_requests ORDER BY id ASC")
        con.close()
        return jsonify([{**r, "created_at": str(r["created_at"])[:10], "type": r.get("type") or "request", "reply": r.get("reply") or ""} for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@book_requests_bp.route("/api/requests/admin")
def api_requests_admin():
    pw = request.headers.get("X-Password", "")
    if not (check_password(pw, "admin") or check_password(pw, "board")):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    rows = fetchall(con, "SELECT id,title,author,reason,room,status,note,votes,created_at,type,reply FROM book_requests ORDER BY id ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10], "type": r.get("type") or "request", "reply": r.get("reply") or "", "note": r.get("note") or ""} for r in rows])


@book_requests_bp.route("/api/requests", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_post_request():
    body = request.get_json()
    title = body.get("title", "").strip()
    req_type = body.get("type", "request")
    default_status = "fb_received" if req_type == "feedback" else "pending"
    if not title:
        return jsonify({"error": "title required"}), 400
    room = body.get("room", "").strip()
    password = body.get("password", "").strip()
    if not room or not password:
        return jsonify({"error": "部屋番号とパスワードでログインしてからリクエストしてください"}), 401
    from services.utils import _verify_password
    con = get_con()
    user = fetchone(con, "SELECT password_hash, password_salt, pin FROM user_accounts WHERE room=?", (room,))
    if not user:
        con.close()
        return jsonify({"error": "部屋番号が未登録です。先にアカウント登録をしてください"}), 401
    ph = user.get("password_hash", "")
    salt = user.get("password_salt", "")
    authed = _verify_password(password, ph, salt) if ph else (user.get("pin") == password)
    if not authed:
        con.close()
        return jsonify({"error": "パスワードが違います"}), 401
    execute(con, "INSERT INTO book_requests (title,author,reason,room,type,status) VALUES (?,?,?,?,?,?)",
        (title, body.get("author","").strip(), body.get("reason","").strip(), room, req_type, default_status))
    con.commit(); con.close()
    return jsonify({"ok": True})


@book_requests_bp.route("/api/requests/<int:req_id>/vote", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_vote_request(req_id):
    con = get_con()
    execute(con, "UPDATE book_requests SET votes = COALESCE(votes,0) + 1 WHERE id=?", (req_id,))
    con.commit()
    row = fetchone(con, "SELECT votes FROM book_requests WHERE id=?", (req_id,))
    con.close()
    return jsonify({"ok": True, "votes": row["votes"] if row else 0})


@book_requests_bp.route("/api/requests/<int:req_id>", methods=["PATCH"])
def api_update_request(req_id):
    body = request.get_json()
    pw = _get_pw()
    if not (check_password(pw, "admin") or check_password(pw, "board")):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    detail_parts = []
    if "status" in body:
        execute(con, "UPDATE book_requests SET status=? WHERE id=?", (body["status"], req_id))
        detail_parts.append(f"status={body['status']}")
    if "note" in body:
        execute(con, "UPDATE book_requests SET note=? WHERE id=?", (body["note"], req_id))
    if "reply" in body:
        execute(con, "UPDATE book_requests SET reply=? WHERE id=?", (body["reply"], req_id))
        detail_parts.append("reply更新")
    con.commit(); con.close()
    log_action("リクエスト対応", f"id={req_id}", ", ".join(detail_parts))
    return jsonify({"ok": True})


@book_requests_bp.route("/api/requests/<int:req_id>", methods=["DELETE"])
def api_delete_request(req_id):
    body = request.get_json()
    pw = _get_pw()
    if not (check_password(pw, "admin") or check_password(pw, "board")):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM book_requests WHERE id=?", (req_id,))
    con.commit(); con.close()
    log_action("リクエスト削除", f"id={req_id}")
    return jsonify({"ok": True})

from flask import Blueprint, request, jsonify
from config import get_board_password
from database import get_con, execute, fetchone, fetchall, USE_PG

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/staff_chat", methods=["GET"])
def api_staff_chat_get():
    pw = request.args.get("password", "")
    if pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    thread_id = request.args.get("thread_id")
    con = get_con()
    if thread_id:
        rows = fetchall(con, "SELECT id, sender, message, image_data, created_at, thread_id FROM staff_chat WHERE thread_id=? ORDER BY created_at DESC LIMIT 200", (int(thread_id),))
    else:
        rows = fetchall(con, "SELECT id, sender, message, image_data, created_at, thread_id FROM staff_chat WHERE thread_id IS NULL ORDER BY created_at DESC LIMIT 100")
    con.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/api/staff_chat", methods=["POST"])
def api_staff_chat_post():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    sender = (body.get("sender") or "匿名").strip()
    message = (body.get("message") or "").strip()
    image_data = (body.get("image_data") or "").strip()
    thread_id = body.get("thread_id")
    if not message and not image_data:
        return jsonify({"error": "message or image required"}), 400
    con = get_con()
    if thread_id:
        execute(con, "INSERT INTO staff_chat (sender, message, image_data, thread_id) VALUES (?, ?, ?, ?)", (sender, message, image_data, int(thread_id)))
    else:
        execute(con, "INSERT INTO staff_chat (sender, message, image_data) VALUES (?, ?, ?)", (sender, message, image_data))
    con.commit(); con.close()
    return jsonify({"ok": True})


@admin_bp.route("/api/staff_chat/<int:msg_id>", methods=["DELETE"])
def api_staff_chat_delete(msg_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM staff_chat WHERE id=?", (msg_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@admin_bp.route("/api/chat_threads", methods=["GET"])
def api_chat_threads_get():
    pw = request.args.get("password", "")
    if pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if USE_PG:
        rows = fetchall(con, """
            SELECT t.id, t.title, t.created_by, t.created_at,
                   COUNT(m.id) AS msg_count,
                   MAX(m.created_at) AS last_at
            FROM chat_threads t
            LEFT JOIN staff_chat m ON m.thread_id = t.id
            GROUP BY t.id, t.title, t.created_by, t.created_at
            ORDER BY COALESCE(MAX(m.created_at), t.created_at) DESC
        """)
    else:
        rows = fetchall(con, """
            SELECT t.id, t.title, t.created_by, t.created_at,
                   COUNT(m.id) AS msg_count,
                   MAX(m.created_at) AS last_at
            FROM chat_threads t
            LEFT JOIN staff_chat m ON m.thread_id = t.id
            GROUP BY t.id
            ORDER BY COALESCE(MAX(m.created_at), t.created_at) DESC
        """)
    con.close()
    return jsonify([{**dict(r), "created_at": str(r["created_at"])[:16], "last_at": str(r["last_at"] or r["created_at"])[:16]} for r in rows])


@admin_bp.route("/api/chat_threads", methods=["POST"])
def api_chat_threads_post():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    title = (body.get("title") or "").strip()
    created_by = (body.get("created_by") or "匿名").strip()
    first_message = (body.get("first_message") or "").strip()
    if not title:
        return jsonify({"error": "タイトルを入力してください"}), 400
    con = get_con()
    if USE_PG:
        cur = execute(con, "INSERT INTO chat_threads (title, created_by) VALUES (?, ?) RETURNING id", (title, created_by))
        thread_id = cur.fetchone()[0]
    else:
        cur = execute(con, "INSERT INTO chat_threads (title, created_by) VALUES (?, ?)", (title, created_by))
        thread_id = cur.lastrowid
    if first_message:
        execute(con, "INSERT INTO staff_chat (sender, message, image_data, thread_id) VALUES (?, ?, '', ?)", (created_by, first_message, thread_id))
    con.commit(); con.close()
    return jsonify({"ok": True, "thread_id": thread_id})


@admin_bp.route("/api/chat_threads/<int:thread_id>", methods=["DELETE"])
def api_chat_threads_delete(thread_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM staff_chat WHERE thread_id=?", (thread_id,))
    execute(con, "DELETE FROM chat_threads WHERE id=?", (thread_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})

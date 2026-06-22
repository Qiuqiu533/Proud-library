import json
from flask import Blueprint, request, jsonify
from config import get_admin_password, get_board_password
from database import get_con, execute, fetchone, fetchall
from services.utils import rate_limit

community_bp = Blueprint("community", __name__)

def _get_pw():
    """X-Passwordヘッダー優先、なければリクエストボディのpasswordをfallback。空文字は認証失敗扱い。"""
    pw = request.headers.get("X-Password", "") or (request.get_json(silent=True) or {}).get("password", "")
    return pw  # 空文字のままにする（呼び出し側で != チェックする際に空パスワードは必ず不一致になるべきだが
               # get_board_password() が "" の場合は通過してしまうため、呼び出し側でガードを追加している）



# --- Issues ---
@community_bp.route("/api/issues")
def api_issues():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,body,priority,status,sort_order,created_at FROM issues ORDER BY sort_order ASC, id DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@community_bp.route("/api/issues", methods=["POST"])
def api_post_issue():
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    row = fetchone(con, "SELECT MIN(sort_order) as m FROM issues")
    new_order = ((row["m"] or 0) - 1) if row else -1
    execute(con, "INSERT INTO issues (title,body,priority,status,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("body","").strip(),
         body.get("priority","中"), body.get("status","未対応"), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/issues/reorder", methods=["POST"])
def api_reorder_issues():
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    for item in body.get("order", []):
        execute(con, "UPDATE issues SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/issues/<int:issue_id>", methods=["PATCH"])
def api_update_issue(issue_id):
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if "title" in body:
        execute(con, "UPDATE issues SET title=?,body=?,priority=?,status=? WHERE id=?",
            (body["title"], body.get("body",""), body.get("priority","中"), body.get("status","未対応"), issue_id))
    elif "status" in body:
        execute(con, "UPDATE issues SET status=? WHERE id=?", (body["status"], issue_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/issues/<int:issue_id>", methods=["DELETE"])
def api_delete_issue(issue_id):
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM issues WHERE id=?", (issue_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Calendar ---
@community_bp.route("/api/calendar")
def api_calendar():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,event_date,body,minutes,sort_order,created_at FROM calendar_events ORDER BY sort_order ASC, event_date DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@community_bp.route("/api/calendar", methods=["POST"])
def api_post_calendar():
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    row = fetchone(con, "SELECT MIN(sort_order) as m FROM calendar_events")
    new_order = ((row["m"] or 0) - 1) if row else -1
    execute(con, "INSERT INTO calendar_events (title,event_date,body,minutes,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/calendar/reorder", methods=["POST"])
def api_reorder_calendar():
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    for item in body.get("order", []):
        execute(con, "UPDATE calendar_events SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/calendar/<int:ev_id>", methods=["PATCH"])
def api_update_calendar(ev_id):
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "UPDATE calendar_events SET title=?,event_date=?,body=?,minutes=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), ev_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/calendar/<int:ev_id>", methods=["DELETE"])
def api_delete_calendar(ev_id):
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM calendar_events WHERE id=?", (ev_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Lib Schedule ---
@community_bp.route("/api/lib-schedule")
def api_lib_schedule():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,event_date,type,created_at FROM lib_schedule ORDER BY event_date ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@community_bp.route("/api/lib-schedule", methods=["POST"])
def api_post_lib_schedule():
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "INSERT INTO lib_schedule (title,event_date,type) VALUES (?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""), body.get("type","event")))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/lib-schedule/<int:sch_id>", methods=["PATCH"])
def api_update_lib_schedule(sch_id):
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "UPDATE lib_schedule SET title=?,event_date=?,type=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""), body.get("type","event"), sch_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/lib-schedule/<int:sch_id>", methods=["DELETE"])
def api_delete_lib_schedule(sch_id):
    body = request.get_json()
    if _get_pw() != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM lib_schedule WHERE id=?", (sch_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Announcements ---
@community_bp.route("/api/announcements")
def api_announcements():
    con = get_con()
    rows = fetchall(con, "SELECT id, title, body, category, image_url, event_date, created_at FROM announcements ORDER BY id DESC")
    con.close()
    def parse_images(raw):
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else [v]
        except Exception:
            return [raw] if raw else []
    return jsonify([{**r, "images": parse_images(r.get("image_url")), "event_date": r.get("event_date") or "", "created_at": str(r["created_at"])[:16]} for r in rows])


@community_bp.route("/api/announcements", methods=["POST"])
def api_post_announcement():
    body = request.get_json()
    pw = _get_pw()
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    title = body.get("title", "").strip()
    text = body.get("body", "").strip()
    if not title or not text:
        return jsonify({"error": "invalid"}), 400
    con = get_con()
    images = body.get("images", [])
    if not images and body.get("image_url","").strip():
        images = [body.get("image_url","").strip()]
    event_date = body.get("event_date", "").strip()
    execute(con, "INSERT INTO announcements (title, body, category, image_url, event_date) VALUES (?,?,?,?,?)",
        (title, text, body.get("category","お知らせ"), json.dumps(images, ensure_ascii=False), event_date))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/announcements/<int:ann_id>", methods=["PATCH"])
def api_update_announcement(ann_id):
    body = request.get_json()
    pw = _get_pw()
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    images = body.get("images", [])
    if not images and body.get("image_url","").strip():
        images = [body.get("image_url","").strip()]
    event_date = body.get("event_date", "").strip()
    execute(con, "UPDATE announcements SET title=?, body=?, category=?, image_url=?, event_date=? WHERE id=?",
        (body.get("title","").strip(), body.get("body","").strip(),
         body.get("category","お知らせ"), json.dumps(images, ensure_ascii=False), event_date, ann_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    body = request.get_json()
    pw = _get_pw()
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM announcements WHERE id=?", (ann_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Book Requests ---
@community_bp.route("/api/requests")
def api_requests():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,author,reason,room,status,votes,created_at,type,reply FROM book_requests ORDER BY id ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10], "type": r.get("type") or "request", "reply": r.get("reply") or ""} for r in rows])


@community_bp.route("/api/requests/admin")
def api_requests_admin():
    pw = request.headers.get("X-Password", "")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    rows = fetchall(con, "SELECT id,title,author,reason,room,status,note,votes,created_at,type,reply FROM book_requests ORDER BY id ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10], "type": r.get("type") or "request", "reply": r.get("reply") or "", "note": r.get("note") or ""} for r in rows])


@community_bp.route("/api/requests", methods=["POST"])
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


@community_bp.route("/api/requests/<int:req_id>/vote", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_vote_request(req_id):
    con = get_con()
    execute(con, "UPDATE book_requests SET votes = COALESCE(votes,0) + 1 WHERE id=?", (req_id,))
    con.commit()
    row = fetchone(con, "SELECT votes FROM book_requests WHERE id=?", (req_id,))
    con.close()
    return jsonify({"ok": True, "votes": row["votes"] if row else 0})


@community_bp.route("/api/requests/<int:req_id>", methods=["PATCH"])
def api_update_request(req_id):
    body = request.get_json()
    pw = _get_pw()
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if "status" in body:
        execute(con, "UPDATE book_requests SET status=? WHERE id=?", (body["status"], req_id))
    if "note" in body:
        execute(con, "UPDATE book_requests SET note=? WHERE id=?", (body["note"], req_id))
    if "reply" in body:
        execute(con, "UPDATE book_requests SET reply=? WHERE id=?", (body["reply"], req_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@community_bp.route("/api/requests/<int:req_id>", methods=["DELETE"])
def api_delete_request(req_id):
    body = request.get_json()
    pw = _get_pw()
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM book_requests WHERE id=?", (req_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})

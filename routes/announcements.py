import json
from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchall
from services.utils import get_pw_from_request as _get_pw, auto_cleanup_images
from services.audit import log_action

announcements_bp = Blueprint("announcements", __name__)


@announcements_bp.route("/api/announcements")
def api_announcements():
    con = get_con()
    try:
        rows = fetchall(con, "SELECT id, title, body, category, image_url, event_date, created_at FROM announcements ORDER BY id DESC")
        con.close()
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500
    def parse_images(raw):
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else [v]
        except Exception:
            return [raw] if raw else []
    return jsonify([{**r, "images": parse_images(r.get("image_url")), "event_date": r.get("event_date") or "", "created_at": str(r["created_at"])[:16]} for r in rows])


@announcements_bp.route("/api/announcements", methods=["POST"])
def api_post_announcement():
    body = request.get_json()
    pw = _get_pw()
    if not (check_password(pw, "admin") or check_password(pw, "board")):
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
    log_action("お知らせ投稿", title)
    if images:
        auto_cleanup_images()
    return jsonify({"ok": True})


@announcements_bp.route("/api/announcements/<int:ann_id>", methods=["PATCH"])
def api_update_announcement(ann_id):
    body = request.get_json()
    pw = _get_pw()
    if not (check_password(pw, "admin") or check_password(pw, "board")):
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
    if images:
        auto_cleanup_images()
    return jsonify({"ok": True})


@announcements_bp.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    body = request.get_json()
    pw = _get_pw()
    if not (check_password(pw, "admin") or check_password(pw, "board")):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM announcements WHERE id=?", (ann_id,))
    con.commit(); con.close()
    log_action("お知らせ削除", f"id={ann_id}")
    return jsonify({"ok": True})

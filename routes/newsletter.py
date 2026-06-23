from flask import Blueprint, request, jsonify
from config import get_board_password, get_admin_password
from database import get_con, execute, fetchall, USE_PG
from services.utils import send_email

newsletter_bp = Blueprint("newsletter", __name__)


def _auth_admin(body):
    pw = (body or {}).get("password", "")
    return pw in (get_board_password(), get_admin_password())


@newsletter_bp.route("/api/newsletter", methods=["GET"])
def api_newsletter_list():
    """送信済み図書館だより一覧（管理者用）。"""
    pw = request.headers.get("X-Password", "")
    if pw not in (get_board_password(), get_admin_password()):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    rows = fetchall(con, "SELECT id, title, sent_count, created_by, created_at FROM newsletters ORDER BY created_at DESC LIMIT 50")
    con.close()
    return jsonify([dict(r) for r in rows])


@newsletter_bp.route("/api/newsletter", methods=["POST"])
def api_newsletter_send():
    """図書館だよりを作成して全住民メールに一斉配信する。"""
    body = request.get_json() or {}
    if not _auth_admin(body):
        return jsonify({"error": "unauthorized"}), 401

    title = (body.get("title") or "").strip()
    content = (body.get("body") or "").strip()
    sender_name = (body.get("sender_name") or "図書館運営チーム").strip()

    if not title or not content:
        return jsonify({"error": "タイトルと本文は必須です"}), 400
    if len(title) > 100:
        return jsonify({"error": "タイトルは100文字以内にしてください"}), 400
    if len(content) > 5000:
        return jsonify({"error": "本文は5000文字以内にしてください"}), 400

    # メールアドレスが登録されている住民を取得
    con = get_con()
    residents = fetchall(con, "SELECT room, email FROM user_accounts WHERE email IS NOT NULL AND email <> ''")
    con.close()

    if not residents:
        return jsonify({"error": "メールアドレス登録済みの住民がいません"}), 400

    subject = f"【プラウド船橋図書館】{title}"
    footer = "\n\n---\nプラウド船橋コミュニティ図書館\nhttps://proud-library.onrender.com/\n※このメールへの返信はできません。"

    sent = 0
    failed = 0
    for r in residents:
        email = r["email"]
        room = r["room"]
        greeting = f"{room}号室の皆様\n\n"
        mail_body = greeting + content + footer
        if send_email(email, subject, mail_body):
            sent += 1
        else:
            failed += 1

    # 送信ログをDBに保存
    con = get_con()
    if USE_PG:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO newsletters (title, body, sent_count, created_by) VALUES (%s, %s, %s, %s)",
            (title, content, sent, sender_name)
        )
    else:
        execute(con, "INSERT INTO newsletters (title, body, sent_count, created_by) VALUES (?, ?, ?, ?)",
                (title, content, sent, sender_name))
    con.commit()
    con.close()

    return jsonify({"ok": True, "sent": sent, "failed": failed})

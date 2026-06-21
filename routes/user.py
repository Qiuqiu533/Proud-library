import json
import secrets
import re as _re
from flask import Blueprint, request, jsonify
from database import get_con, execute, fetchone, USE_PG
from services.utils import _hash_password, _verify_password, _send_reset_email

user_bp = Blueprint("user", __name__)

_ROOM_PATTERN = _re.compile(r'^[1-5]-\d{3,4}$|^\d{6}$')


def _validate_room(room):
    """部屋番号バリデーション: 街区形式(1-533)または6桁数字"""
    return bool(_ROOM_PATTERN.match(room))


def _user_auth_ok(user, password):
    """パスワードハッシュで認証。旧PIN方式にも対応"""
    if user.get("password_hash") and user.get("password_salt"):
        return _verify_password(password, user["password_hash"], user["password_salt"])
    return user.get("pin") == password


@user_bp.route("/api/user/register", methods=["POST"])
def api_user_register():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or "").strip()
    email    = (body.get("email")    or "").strip()
    if not room or not password or len(password) < 6:
        return jsonify({"error": "部屋番号と6文字以上のパスワードを入力してください"}), 400
    if not _validate_room(room):
        return jsonify({"error": "部屋番号の形式が正しくありません（例：5-533 または 6桁数字）"}), 400
    con = get_con()
    user = fetchone(con, "SELECT room, password_hash FROM user_accounts WHERE room=?", (room,))
    if user and user.get("password_hash"):
        con.close()
        return jsonify({"error": "この部屋番号はすでに登録されています"}), 409
    h, s = _hash_password(password)
    if user is None:
        execute(con, "INSERT INTO user_accounts (room, pin, email, password_hash, password_salt) VALUES (?,?,?,?,?)",
                (room, password, email, h, s))
    else:
        if USE_PG:
            execute(con, "UPDATE user_accounts SET email=?, password_hash=?, password_salt=?, updated_at=NOW() WHERE room=?", (email, h, s, room))
        else:
            execute(con, "UPDATE user_accounts SET email=?, password_hash=?, password_salt=?, updated_at=datetime('now','localtime') WHERE room=?", (email, h, s, room))
    con.commit(); con.close()
    return jsonify({"ok": True, "is_new": True})


@user_bp.route("/api/user/login", methods=["POST"])
def api_user_login():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or body.get("pin") or "").strip()
    if not room or not password:
        return jsonify({"error": "部屋番号とパスワードを入力してください"}), 400
    if not _validate_room(room):
        return jsonify({"error": "部屋番号の形式が正しくありません"}), 400
    con = get_con()
    user = fetchone(con, "SELECT room, pin, email, password_hash, password_salt, favorites, reading_log, library_card_url, library_card_image FROM user_accounts WHERE room=?", (room,))
    if user is None:
        con.close()
        return jsonify({"error": "この部屋番号は未登録です。まず新規登録してください"}), 404
    if not _user_auth_ok(user, password):
        con.close()
        return jsonify({"error": "パスワードが違います"}), 401
    con.close()
    return jsonify({
        "ok": True,
        "room": user["room"],
        "email": user.get("email") or "",
        "favorites": json.loads(user["favorites"] or "[]"),
        "reading_log": json.loads(user["reading_log"] or "{}"),
        "library_card_url": user.get("library_card_url") or "",
        "library_card_image": user.get("library_card_image") or ""
    })


@user_bp.route("/api/user/sync", methods=["POST"])
def api_user_sync():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or body.get("pin") or "").strip()
    if not room or not password:
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    user = fetchone(con, "SELECT pin, password_hash, password_salt FROM user_accounts WHERE room=?", (room,))
    if not user or not _user_auth_ok(user, password):
        con.close()
        return jsonify({"error": "unauthorized"}), 401
    favs = json.dumps(body.get("favorites", []), ensure_ascii=False)
    rlog = json.dumps(body.get("reading_log", {}), ensure_ascii=False)
    card_url = (body.get("library_card_url") or "")[:2000]
    card_img = body.get("library_card_image") or ""
    if USE_PG:
        execute(con, "UPDATE user_accounts SET favorites=?, reading_log=?, library_card_url=?, library_card_image=?, updated_at=NOW() WHERE room=?",
                (favs, rlog, card_url, card_img, room))
    else:
        execute(con, "UPDATE user_accounts SET favorites=?, reading_log=?, library_card_url=?, library_card_image=?, updated_at=datetime('now','localtime') WHERE room=?",
                (favs, rlog, card_url, card_img, room))
    con.commit(); con.close()
    return jsonify({"ok": True})


@user_bp.route("/api/user/update-email", methods=["POST"])
def api_user_update_email():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or body.get("pin") or "").strip()
    email    = (body.get("email")    or "").strip()
    if not room or not password or not email:
        return jsonify({"error": "入力が不足しています"}), 400
    con = get_con()
    user = fetchone(con, "SELECT pin, password_hash, password_salt FROM user_accounts WHERE room=?", (room,))
    if not user or not _user_auth_ok(user, password):
        con.close()
        return jsonify({"error": "認証に失敗しました"}), 401
    if USE_PG:
        execute(con, "UPDATE user_accounts SET email=?, updated_at=NOW() WHERE room=?", (email, room))
    else:
        execute(con, "UPDATE user_accounts SET email=?, updated_at=datetime('now','localtime') WHERE room=?", (email, room))
    con.commit(); con.close()
    return jsonify({"ok": True})


@user_bp.route("/api/user/change-password", methods=["POST"])
def api_user_change_password():
    body = request.get_json()
    room         = (body.get("room")         or "").strip()
    old_password = (body.get("old_password") or "").strip()
    new_password = (body.get("new_password") or "").strip()
    if not room or not old_password or not new_password or len(new_password) < 6:
        return jsonify({"error": "6文字以上の新しいパスワードを入力してください"}), 400
    con = get_con()
    user = fetchone(con, "SELECT pin, password_hash, password_salt FROM user_accounts WHERE room=?", (room,))
    if not user or not _user_auth_ok(user, old_password):
        con.close()
        return jsonify({"error": "現在のパスワードが違います"}), 401
    h, s = _hash_password(new_password)
    if USE_PG:
        execute(con, "UPDATE user_accounts SET password_hash=?, password_salt=?, pin=?, updated_at=NOW() WHERE room=?", (h, s, new_password, room))
    else:
        execute(con, "UPDATE user_accounts SET password_hash=?, password_salt=?, pin=?, updated_at=datetime('now','localtime') WHERE room=?", (h, s, new_password, room))
    con.commit(); con.close()
    return jsonify({"ok": True})


@user_bp.route("/api/user/forgot-password", methods=["POST"])
def api_user_forgot_password():
    body  = request.get_json()
    room  = (body.get("room")  or "").strip()
    email = (body.get("email") or "").strip()
    if not room or not email:
        return jsonify({"error": "部屋番号とメールアドレスを入力してください"}), 400
    con = get_con()
    user = fetchone(con, "SELECT email FROM user_accounts WHERE room=?", (room,))
    if not user or (user.get("email") or "").lower() != email.lower():
        con.close()
        return jsonify({"error": "部屋番号またはメールアドレスが一致しません"}), 400
    token = secrets.token_urlsafe(32)
    if USE_PG:
        execute(con, "INSERT INTO password_reset_tokens (token, room, expires_at) VALUES (?, ?, NOW() + INTERVAL '30 minutes')", (token, room))
    else:
        execute(con, "INSERT INTO password_reset_tokens (token, room, expires_at) VALUES (?, ?, datetime('now','+30 minutes'))", (token, room))
    con.commit(); con.close()
    return jsonify({"ok": True, "token": token})


@user_bp.route("/api/user/reset-password", methods=["POST"])
def api_user_reset_password():
    body     = request.get_json()
    token    = (body.get("token")    or "").strip()
    password = (body.get("password") or "").strip()
    if not token or not password or len(password) < 6:
        return jsonify({"error": "6文字以上の新しいパスワードを入力してください"}), 400
    con = get_con()
    row = fetchone(con, "SELECT room, expires_at, used FROM password_reset_tokens WHERE token=?", (token,))
    if not row:
        con.close()
        return jsonify({"error": "無効なリンクです"}), 400
    if row["used"]:
        con.close()
        return jsonify({"error": "このリンクはすでに使用済みです"}), 400
    if USE_PG:
        exp_check = fetchone(con, "SELECT (expires_at < NOW()) AS expired FROM password_reset_tokens WHERE token=?", (token,))
        if exp_check and exp_check["expired"]:
            con.close()
            return jsonify({"error": "リンクの有効期限が切れています。再度お申し込みください"}), 400
    else:
        exp_check = fetchone(con, "SELECT (expires_at < datetime('now')) AS expired FROM password_reset_tokens WHERE token=?", (token,))
        if exp_check and exp_check["expired"]:
            con.close()
            return jsonify({"error": "リンクの有効期限が切れています。再度お申し込みください"}), 400
    room = row["room"]
    h, s = _hash_password(password)
    if USE_PG:
        execute(con, "UPDATE user_accounts SET password_hash=?, password_salt=?, pin=?, updated_at=NOW() WHERE room=?", (h, s, password, room))
        execute(con, "UPDATE password_reset_tokens SET used=TRUE WHERE token=?", (token,))
    else:
        execute(con, "UPDATE user_accounts SET password_hash=?, password_salt=?, pin=?, updated_at=datetime('now','localtime') WHERE room=?", (h, s, password, room))
        execute(con, "UPDATE password_reset_tokens SET used=1 WHERE token=?", (token,))
    con.commit(); con.close()
    return jsonify({"ok": True})

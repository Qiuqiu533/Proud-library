import json
import secrets
import re as _re
from flask import Blueprint, request, jsonify
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.utils import _hash_password, _verify_password, _send_reset_email, _is_bcrypt_hash

user_bp = Blueprint("user", __name__)

_ROOM_PATTERN = _re.compile(r'^[1-5]-\d{3,4}$|^\d{6}$')


def _validate_room(room):
    """部屋番号バリデーション: 街区形式(1-533)または6桁数字"""
    return bool(_ROOM_PATTERN.match(room))


def _user_auth_ok(user, password):
    """パスワードハッシュで認証。bcrypt・旧SHA-256・PIN の3方式に対応。"""
    ph = user.get("password_hash", "")
    salt = user.get("password_salt", "")
    if ph:
        return _verify_password(password, ph, salt)
    return user.get("pin") == password


def _upgrade_to_bcrypt_if_needed(con, room, password, password_hash):
    """旧 SHA-256 ハッシュなら bcrypt に再ハッシュしてDBを更新（ログイン成功後に呼ぶ）。"""
    if _is_bcrypt_hash(password_hash):
        return
    new_hash, _ = _hash_password(password)
    if USE_PG:
        execute(con, "UPDATE user_accounts SET password_hash=?, password_salt='', updated_at=NOW() WHERE room=?", (new_hash, room))
    else:
        execute(con, "UPDATE user_accounts SET password_hash=?, password_salt='', updated_at=datetime('now','localtime') WHERE room=?", (new_hash, room))
    con.commit()


@user_bp.route("/api/user/register", methods=["POST"])
def api_user_register():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or "").strip()
    email    = (body.get("email")    or "").strip()
    if not room or not password or len(password) < 8:
        return jsonify({"error": "部屋番号と8文字以上のパスワードを入力してください"}), 400
    if not _validate_room(room):
        return jsonify({"error": "部屋番号の形式が正しくありません（例：5-533 または 6桁数字）"}), 400
    con = get_con()
    try:
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
    except Exception as e:
        con.close()
        return jsonify({"error": "登録処理中にエラーが発生しました。しばらく後に再試行してください"}), 500


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
    try:
        user = fetchone(con, "SELECT room, pin, email, password_hash, password_salt, favorites, reading_log, library_card_url, library_card_image FROM user_accounts WHERE room=?", (room,))
        if user is None:
            con.close()
            return jsonify({"error": "この部屋番号は未登録です。まず新規登録してください"}), 404
        if not _user_auth_ok(user, password):
            con.close()
            return jsonify({"error": "パスワードが違います"}), 401
        _upgrade_to_bcrypt_if_needed(con, room, password, user.get("password_hash", ""))
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
    except Exception as e:
        con.close()
        return jsonify({"error": "ログイン処理中にエラーが発生しました。しばらく後に再試行してください"}), 500


@user_bp.route("/api/user/sync", methods=["POST"])
def api_user_sync():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or body.get("pin") or "").strip()
    if not room or not password:
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
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
    except Exception:
        con.close()
        return jsonify({"error": "同期処理中にエラーが発生しました"}), 500


@user_bp.route("/api/user/update-email", methods=["POST"])
def api_user_update_email():
    body = request.get_json()
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or body.get("pin") or "").strip()
    email    = (body.get("email")    or "").strip()
    if not room or not password or not email:
        return jsonify({"error": "入力が不足しています"}), 400
    con = get_con()
    try:
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
    except Exception:
        con.close()
        return jsonify({"error": "メール更新中にエラーが発生しました"}), 500


@user_bp.route("/api/user/change-password", methods=["POST"])
def api_user_change_password():
    body = request.get_json()
    room         = (body.get("room")         or "").strip()
    old_password = (body.get("old_password") or "").strip()
    new_password = (body.get("new_password") or "").strip()
    if not room or not old_password or not new_password or len(new_password) < 6:
        return jsonify({"error": "8文字以上の新しいパスワードを入力してください"}), 400
    con = get_con()
    try:
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
    except Exception:
        con.close()
        return jsonify({"error": "パスワード変更中にエラーが発生しました"}), 500


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
    if not token or not password or len(password) < 8:
        return jsonify({"error": "8文字以上の新しいパスワードを入力してください"}), 400
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


# --- Wish List ---
def _wish_auth(body):
    """room + password で住民認証。成功時 room を返す、失敗時 None。"""
    from services.utils import _verify_password as vp, _is_bcrypt_hash
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or "").strip()
    if not room or not password:
        return None
    con = get_con()
    user = fetchone(con, "SELECT password_hash, password_salt, pin FROM user_accounts WHERE room=?", (room,))
    con.close()
    if not user:
        return None
    ph   = user.get("password_hash", "")
    salt = user.get("password_salt", "")
    if ph:
        return room if vp(password, ph, salt) else None
    return room if user.get("pin") == password else None


@user_bp.route("/api/wishlist")
def api_get_wishlist():
    room     = request.args.get("room", "").strip()
    password = request.headers.get("X-Password", "").strip()
    if not room or not password:
        return jsonify({"error": "unauthorized"}), 401
    authed = _wish_auth({"room": room, "password": password})
    if not authed:
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    items = fetchall(con, "SELECT isbn, created_at FROM wish_list WHERE room=? ORDER BY id DESC", (room,))
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in items])


@user_bp.route("/api/wishlist", methods=["POST"])
def api_add_wishlist():
    body = request.get_json() or {}
    room = _wish_auth(body)
    if not room:
        return jsonify({"error": "unauthorized"}), 401
    isbn = (body.get("isbn") or "").strip()
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    try:
        if USE_PG:
            execute(con, "INSERT INTO wish_list (room, isbn) VALUES (?,?) ON CONFLICT (room, isbn) DO NOTHING", (room, isbn))
        else:
            execute(con, "INSERT OR IGNORE INTO wish_list (room, isbn) VALUES (?,?)", (room, isbn))
        con.commit()
    except Exception:
        con.close()
        return jsonify({"error": "db error"}), 500
    con.close()
    return jsonify({"ok": True})


@user_bp.route("/api/wishlist", methods=["DELETE"])
def api_delete_wishlist():
    body = request.get_json() or {}
    room = _wish_auth(body)
    if not room:
        return jsonify({"error": "unauthorized"}), 401
    isbn = (body.get("isbn") or "").strip()
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "DELETE FROM wish_list WHERE room=? AND isbn=?", (room, isbn))
    con.commit(); con.close()
    return jsonify({"ok": True})

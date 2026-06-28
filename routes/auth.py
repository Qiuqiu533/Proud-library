from flask import Blueprint, request, jsonify
from config import get_admin_password, get_resident_password, get_board_password, check_password
from database import get_con, execute, fetchone
from services.utils import rate_limit, _hash_password, _verify_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_auth():
    body = request.get_json()
    if check_password(body.get("password"), "resident"):
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401



@auth_bp.route("/api/board/auth", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_board_auth():
    body = request.get_json()
    if check_password(body.get("password"), "board"):
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401


@auth_bp.route("/api/admin/login", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_admin_login():
    body = request.get_json()
    code = (body.get("code") or "").strip().upper()
    password = body.get("password") or ""
    if not code or not password:
        return jsonify({"error": "コードとパスワードを入力してください"}), 400
    con = get_con()
    row = fetchone(con, "SELECT id,code,name,password_hash,salt,role FROM admin_users WHERE code=?", (code,))
    con.close()
    if not row or not _verify_password(password, row["password_hash"], row["salt"]):
        return jsonify({"error": "コードまたはパスワードが正しくありません"}), 401
    return jsonify({"ok": True, "code": row["code"], "name": row["name"], "role": row["role"]})


@auth_bp.route("/api/admin/users", methods=["GET"])
def api_admin_users_list():
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from database import fetchall
    con = get_con()
    rows = fetchall(con, "SELECT id,code,name,role,created_at FROM admin_users ORDER BY id ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@auth_bp.route("/api/admin/users", methods=["POST"])
@rate_limit(limit=20, window=60)
def api_admin_users_create():
    body = request.get_json()
    req_code = (body.get("req_code") or "").strip().upper()
    req_pass = body.get("req_password") or ""
    con = get_con()
    req_row = fetchone(con, "SELECT role,password_hash,salt FROM admin_users WHERE code=?", (req_code,))
    if not req_row or req_row["role"] != "master" or not _verify_password(req_pass, req_row["password_hash"], req_row["salt"]):
        con.close()
        return jsonify({"error": "マスター権限が必要です"}), 403
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""
    role = body.get("role") or "admin"
    if role not in ("master", "admin"):
        role = "admin"
    if not code or not name or not password:
        con.close()
        return jsonify({"error": "コード・氏名・パスワードは必須です"}), 400
    if len(password) < 6:
        con.close()
        return jsonify({"error": "パスワードは6文字以上にしてください"}), 400
    existing = fetchone(con, "SELECT id FROM admin_users WHERE code=?", (code,))
    if existing:
        con.close()
        return jsonify({"error": "そのコードは既に使用されています"}), 409
    h, s = _hash_password(password)
    execute(con, "INSERT INTO admin_users (code,name,password_hash,salt,role) VALUES (?,?,?,?,?)",
            (code, name, h, s, role))
    con.commit(); con.close()
    return jsonify({"ok": True})


@auth_bp.route("/api/admin/users/<string:target_code>", methods=["DELETE"])
def api_admin_users_delete(target_code):
    body = request.get_json()
    req_code = (body.get("req_code") or "").strip().upper()
    req_pass = body.get("req_password") or ""
    con = get_con()
    req_row = fetchone(con, "SELECT role,password_hash,salt FROM admin_users WHERE code=?", (req_code,))
    if not req_row or req_row["role"] != "master" or not _verify_password(req_pass, req_row["password_hash"], req_row["salt"]):
        con.close()
        return jsonify({"error": "マスター権限が必要です"}), 403
    if target_code.upper() == req_code:
        con.close()
        return jsonify({"error": "自分自身は削除できません"}), 400
    execute(con, "DELETE FROM admin_users WHERE code=?", (target_code.upper(),))
    con.commit(); con.close()
    return jsonify({"ok": True})


@auth_bp.route("/api/admin/users/<string:target_code>/password", methods=["PATCH"])
@rate_limit(limit=10, window=60)
def api_admin_users_change_password(target_code):
    body = request.get_json()
    req_code = (body.get("req_code") or "").strip().upper()
    req_pass = body.get("req_password") or ""
    new_pw = body.get("new_password") or ""
    if len(new_pw) < 6:
        return jsonify({"error": "パスワードは6文字以上にしてください"}), 400
    con = get_con()
    req_row = fetchone(con, "SELECT role,password_hash,salt FROM admin_users WHERE code=?", (req_code,))
    if not req_row or not _verify_password(req_pass, req_row["password_hash"], req_row["salt"]):
        con.close()
        return jsonify({"error": "現在のパスワードが正しくありません"}), 401
    is_self = req_code == target_code.upper()
    is_master = req_row["role"] == "master"
    if not is_self and not is_master:
        con.close()
        return jsonify({"error": "権限がありません"}), 403
    h, s = _hash_password(new_pw)
    execute(con, "UPDATE admin_users SET password_hash=?,salt=? WHERE code=?", (h, s, target_code.upper()))
    con.commit(); con.close()
    return jsonify({"ok": True})


@auth_bp.route("/api/admin/change-password", methods=["POST"])
def api_change_password():
    body = request.get_json()
    if not check_password(body.get("current_password"), "board"):
        return jsonify({"error": "現在のパスワードが違います"}), 401
    target = body.get("target")
    new_pw = body.get("new_password", "").strip()
    if not new_pw or len(new_pw) < 4:
        return jsonify({"error": "4文字以上で入力してください"}), 400
    key_map = {"resident": "resident_password", "admin": "admin_password", "board": "board_password"}
    if target not in key_map:
        return jsonify({"error": "不正なターゲット"}), 400
    db_key = key_map[target]
    from database import USE_PG
    con = get_con()
    if USE_PG:
        execute(con, "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (db_key, new_pw))
    else:
        execute(con, "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (db_key, new_pw))
    con.commit(); con.close()
    return jsonify({"ok": True})

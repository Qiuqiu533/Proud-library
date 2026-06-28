import secrets
from flask import Blueprint, request, jsonify
from config import get_board_password, check_password
from database import get_con, execute, fetchone, fetchall, USE_PG

invite_bp = Blueprint("invite", __name__)

_CODE_LEN = 8  # 例: "AB3K9ZXQ"


def _gen_code() -> str:
    """衝突しにくい8文字英数字コードを生成"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 紛らわしい文字を除外
    return "".join(secrets.choice(alphabet) for _ in range(_CODE_LEN))


def _auth(req) -> bool:
    return check_password(req.headers.get("X-Password"), "board")


# ===== 管理者向け =====

@invite_bp.route("/api/admin/invite-codes", methods=["GET"])
def api_list_invite_codes():
    """招待コード一覧（管理者）"""
    if not _auth(request):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        rows = fetchall(con, "SELECT id, code, note, used_room, used_at, expires_at, created_at FROM invite_codes ORDER BY id DESC")
        con.close()
        return jsonify([{
            "id": r["id"],
            "code": r["code"],
            "note": r["note"] or "",
            "used_room": r["used_room"] or "",
            "used_at": str(r["used_at"])[:16] if r["used_at"] else "",
            "expires_at": str(r["expires_at"])[:10] if r["expires_at"] else "",
            "created_at": str(r["created_at"])[:10],
        } for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@invite_bp.route("/api/admin/invite-codes", methods=["POST"])
def api_create_invite_codes():
    """招待コードを一括生成（管理者）"""
    if not _auth(request):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    count = min(int(body.get("count", 1)), 50)
    note = (body.get("note") or "").strip()[:100]
    expires_at = (body.get("expires_at") or "").strip() or None

    con = get_con()
    codes = []
    try:
        for _ in range(count):
            code = _gen_code()
            if USE_PG:
                execute(con, """
                    INSERT INTO invite_codes (code, note, expires_at)
                    VALUES (%s, %s, %s)
                """, (code, note, expires_at))
            else:
                execute(con, """
                    INSERT INTO invite_codes (code, note, expires_at)
                    VALUES (?, ?, ?)
                """, (code, note, expires_at))
            codes.append(code)
        con.commit()
        con.close()
        return jsonify({"ok": True, "codes": codes})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@invite_bp.route("/api/admin/invite-codes/<int:code_id>", methods=["DELETE"])
def api_delete_invite_code(code_id):
    """未使用の招待コードを削除（管理者）"""
    if not _auth(request):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        row = fetchone(con, f"SELECT used_room FROM invite_codes WHERE id={ph}", (code_id,))
        if not row:
            con.close()
            return jsonify({"error": "not found"}), 404
        if row["used_room"]:
            con.close()
            return jsonify({"error": "使用済みのコードは削除できません"}), 400
        execute(con, f"DELETE FROM invite_codes WHERE id={ph}", (code_id,))
        con.commit()
        con.close()
        return jsonify({"ok": True})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


# ===== 住民向け（登録時の検証） =====

@invite_bp.route("/api/invite/validate", methods=["POST"])
def api_validate_invite_code():
    """登録前に招待コードの有効性を確認（住民）"""
    body = request.get_json() or {}
    code = (body.get("code") or "").strip().upper()
    if not code:
        return jsonify({"valid": False, "error": "コードを入力してください"}), 400
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        if USE_PG:
            row = fetchone(con, f"""
                SELECT id, used_room, expires_at FROM invite_codes
                WHERE code={ph} AND (expires_at IS NULL OR expires_at > NOW())
            """, (code,))
        else:
            row = fetchone(con, f"""
                SELECT id, used_room, expires_at FROM invite_codes
                WHERE code={ph} AND (expires_at IS NULL OR expires_at > datetime('now'))
            """, (code,))
        con.close()
        if not row:
            return jsonify({"valid": False, "error": "招待コードが無効または期限切れです"}), 400
        if row["used_room"]:
            return jsonify({"valid": False, "error": "このコードはすでに使用されています"}), 400
        return jsonify({"valid": True})
    except Exception as e:
        con.close()
        return jsonify({"valid": False, "error": str(e)}), 500

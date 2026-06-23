from flask import Blueprint, request, jsonify
from database import get_con, execute, fetchall, fetchone, USE_PG
from config import get_resident_password
from services.utils import rate_limit

timeline_bp = Blueprint("timeline", __name__)


def _auth(body):
    u = body or {}
    room = (u.get("room") or "").strip()
    pw = (u.get("password") or "").strip()
    if not room or not pw:
        return None
    con = get_con()
    row = fetchone(con, "SELECT room, pin, password_hash, password_salt FROM user_accounts WHERE room=?", (room,))
    con.close()
    if not row:
        return None
    from services.utils import _verify_password, _is_bcrypt_hash
    if _is_bcrypt_hash(row.get("password_hash") or ""):
        if not _verify_password(pw, row["password_hash"], row.get("password_salt") or ""):
            return None
    else:
        if pw != (row.get("pin") or get_resident_password()):
            return None
    return room


@timeline_bp.route("/api/timeline", methods=["GET"])
def api_timeline_list():
    """タイムライン一覧を返す（最新50件）。"""
    con = get_con()
    try:
        rows = fetchall(con, """
            SELECT id, isbn, title, author, cover, status, comment, nickname, created_at
            FROM reading_timeline ORDER BY created_at DESC LIMIT 50
        """)
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "isbn": r["isbn"],
                "title": r["title"],
                "author": r["author"],
                "cover": r["cover"],
                "status": r["status"],
                "comment": r["comment"],
                "nickname": r["nickname"] or "住民",
                "created_at": str(r["created_at"])[:10],
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


@timeline_bp.route("/api/timeline", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_timeline_post():
    """読書記録をタイムラインにシェアする。"""
    body = request.get_json()
    room = _auth(body)
    if not room:
        return jsonify({"error": "認証エラー"}), 401

    isbn    = (body.get("isbn")     or "").strip()
    title   = (body.get("title")    or "").strip()
    author  = (body.get("author")   or "").strip()
    cover   = (body.get("cover")    or "").strip()
    status  = (body.get("status")   or "").strip()
    comment = (body.get("comment")  or "").strip()[:200]
    nickname = (body.get("nickname") or "").strip()[:20]

    if not isbn or status not in ("読んだ", "読書中", "読みたい", "借り中"):
        return jsonify({"error": "ISBN・ステータスは必須です"}), 400

    con = get_con()
    # 同一room+isbnの既存投稿は更新
    existing = fetchone(con, "SELECT id FROM reading_timeline WHERE room=? AND isbn=?", (room, isbn))
    if existing:
        execute(con, """
            UPDATE reading_timeline SET status=?, comment=?, nickname=?, title=?, author=?, cover=?
            WHERE room=? AND isbn=?
        """, (status, comment, nickname, title, author, cover, room, isbn))
    else:
        execute(con, """
            INSERT INTO reading_timeline (room, isbn, title, author, cover, status, comment, nickname)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (room, isbn, title, author, cover, status, comment, nickname))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@timeline_bp.route("/api/timeline/<int:post_id>", methods=["DELETE"])
def api_timeline_delete(post_id):
    """自分の投稿を削除する。"""
    body = request.get_json()
    room = _auth(body)
    if not room:
        return jsonify({"error": "認証エラー"}), 401
    con = get_con()
    row = fetchone(con, "SELECT room FROM reading_timeline WHERE id=?", (post_id,))
    if not row or row["room"] != room:
        con.close()
        return jsonify({"error": "投稿が見つかりません"}), 404
    execute(con, "DELETE FROM reading_timeline WHERE id=?", (post_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True})

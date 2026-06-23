from flask import Blueprint, request, jsonify
from database import get_con, execute, fetchall, fetchone, USE_PG
from config import get_resident_password
from services.utils import rate_limit
import logging

logger = logging.getLogger(__name__)
timeline_bp = Blueprint("timeline", __name__)


def _ensure_table():
    """reading_timeline テーブルが存在しない場合に作成する。"""
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reading_timeline (
                    id SERIAL PRIMARY KEY,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    cover TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    comment TEXT DEFAULT '',
                    nickname TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_created ON reading_timeline(created_at DESC)")
        else:
            con.execute("""CREATE TABLE IF NOT EXISTS reading_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL,
                isbn TEXT NOT NULL, title TEXT DEFAULT '', author TEXT DEFAULT '',
                cover TEXT DEFAULT '', status TEXT NOT NULL, comment TEXT DEFAULT '',
                nickname TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        con.commit()
    except Exception as e:
        logger.error("[timeline] _ensure_table error: %s", e)
    finally:
        con.close()


def _auth(body):
    u = body or {}
    room = (u.get("room") or "").strip()
    pw = (u.get("password") or "").strip()
    if not room or not pw:
        return None
    ph = "%s" if USE_PG else "?"
    con = get_con()
    row = fetchone(con, f"SELECT room, pin, password_hash, password_salt FROM user_accounts WHERE room={ph}", (room,))
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
    _ensure_table()
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
    _ensure_table()
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

    if not isbn:
        return jsonify({"error": "ISBNは必須です"}), 400
    if status not in ("読んだ", "読書中", "読みたい", "借り中"):
        return jsonify({"error": f"ステータスが不正です: '{status}'"}), 400

    con = get_con()
    try:
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
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        con.close()


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

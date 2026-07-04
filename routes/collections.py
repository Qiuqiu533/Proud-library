import json
import logging
from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchall, USE_PG

logger = logging.getLogger(__name__)

collections_bp = Blueprint("collections", __name__)


def _ensure_collections_table():
    """collections テーブルと sort_order カラムを保証する。"""
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS collections (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    emoji TEXT DEFAULT '📚',
                    isbns TEXT DEFAULT '[]',
                    is_active BOOLEAN DEFAULT TRUE,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE collections ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0")
        else:
            try:
                con.execute("""CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    description TEXT DEFAULT '', emoji TEXT DEFAULT '📚',
                    isbns TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now','localtime')))""")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE collections ADD COLUMN sort_order INTEGER DEFAULT 0")
            except Exception:
                pass
        con.commit()
    except Exception as e:
        logger.error("[collections] _ensure_table error: %s", e)
    finally:
        con.close()


@collections_bp.route("/api/collections")
def api_collections_get():
    _ensure_collections_table()
    con = get_con()
    show_all = request.args.get("all") == "1"
    try:
        if show_all:
            rows = fetchall(con, "SELECT id, title, description, emoji, isbns, is_active, sort_order FROM collections ORDER BY sort_order, id")
        else:
            rows = fetchall(con, "SELECT id, title, description, emoji, isbns, is_active, sort_order FROM collections WHERE is_active=? ORDER BY sort_order, id", (True if USE_PG else 1,))
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500
    con.close()
    result = []
    for r in rows:
        try:
            isbns = json.loads(r["isbns"]) if isinstance(r["isbns"], str) else (r["isbns"] or [])
        except Exception:
            isbns = []
        result.append({**r, "isbns": isbns, "count": len(isbns)})
    return jsonify(result)


@collections_bp.route("/api/collections", methods=["POST"])
def api_collections_post():
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    title = (body.get("title") or "").strip()
    if not title:
        return jsonify({"error": "タイトルを入力してください"}), 400
    description = (body.get("description") or "").strip()
    emoji = (body.get("emoji") or "📚").strip()
    isbns = body.get("isbns") or []
    sort_order = int(body.get("sort_order") or 0)
    con = get_con()
    if USE_PG:
        cur = execute(con, "INSERT INTO collections (title, description, emoji, isbns, sort_order) VALUES (?,?,?,?,?) RETURNING id",
                      (title, description, emoji, json.dumps(isbns, ensure_ascii=False), sort_order))
        cid = cur.fetchone()[0]
    else:
        cur = execute(con, "INSERT INTO collections (title, description, emoji, isbns, sort_order) VALUES (?,?,?,?,?)",
                      (title, description, emoji, json.dumps(isbns, ensure_ascii=False), sort_order))
        cid = cur.lastrowid
    con.commit(); con.close()
    return jsonify({"ok": True, "id": cid})


@collections_bp.route("/api/collections/<int:cid>", methods=["PATCH"])
def api_collections_patch(cid):
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    updates = []
    params = []
    for field in ("title", "description", "emoji", "sort_order"):
        if field in body:
            updates.append(f"{field}=?")
            params.append(body[field])
    if "isbns" in body:
        updates.append("isbns=?")
        params.append(json.dumps(body["isbns"], ensure_ascii=False))
    if "is_active" in body:
        updates.append("is_active=?")
        params.append(body["is_active"])
    if not updates:
        return jsonify({"ok": True})
    params.append(cid)
    con = get_con()
    execute(con, f"UPDATE collections SET {','.join(updates)} WHERE id=?", tuple(params))
    con.commit(); con.close()
    return jsonify({"ok": True})


@collections_bp.route("/api/collections/<int:cid>", methods=["DELETE"])
def api_collections_delete(cid):
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM collections WHERE id=?", (cid,))
    con.commit(); con.close()
    return jsonify({"ok": True})

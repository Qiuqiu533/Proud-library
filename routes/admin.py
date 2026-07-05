from flask import Blueprint, request, jsonify
from config import get_board_password, check_password, get_setting
from database import get_con, execute, fetchone, fetchall, USE_PG

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/staff_chat", methods=["GET"])
def api_staff_chat_get():
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    thread_id = request.args.get("thread_id")
    con = get_con()
    if thread_id:
        rows = fetchall(con, "SELECT id, sender, message, image_data, created_at, thread_id FROM staff_chat WHERE thread_id=? ORDER BY created_at DESC LIMIT 200", (int(thread_id),))
    else:
        rows = fetchall(con, "SELECT id, sender, message, image_data, created_at, thread_id FROM staff_chat WHERE thread_id IS NULL ORDER BY created_at DESC LIMIT 100")
    con.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/api/staff_chat", methods=["POST"])
def api_staff_chat_post():
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    sender = (body.get("sender") or "匿名").strip()
    message = (body.get("message") or "").strip()
    image_data = (body.get("image_data") or "").strip()
    thread_id = body.get("thread_id")
    if not message and not image_data:
        return jsonify({"error": "message or image required"}), 400
    con = get_con()
    if thread_id:
        execute(con, "INSERT INTO staff_chat (sender, message, image_data, thread_id) VALUES (?, ?, ?, ?)", (sender, message, image_data, int(thread_id)))
    else:
        execute(con, "INSERT INTO staff_chat (sender, message, image_data) VALUES (?, ?, ?)", (sender, message, image_data))
    con.commit(); con.close()
    return jsonify({"ok": True})


@admin_bp.route("/api/staff_chat/<int:msg_id>", methods=["DELETE"])
def api_staff_chat_delete(msg_id):
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM staff_chat WHERE id=?", (msg_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@admin_bp.route("/api/chat_threads", methods=["GET"])
def api_chat_threads_get():
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if USE_PG:
        rows = fetchall(con, """
            SELECT t.id, t.title, t.created_by, t.created_at,
                   COUNT(m.id) AS msg_count,
                   MAX(m.created_at) AS last_at
            FROM chat_threads t
            LEFT JOIN staff_chat m ON m.thread_id = t.id
            GROUP BY t.id, t.title, t.created_by, t.created_at
            ORDER BY COALESCE(MAX(m.created_at), t.created_at) DESC
        """)
    else:
        rows = fetchall(con, """
            SELECT t.id, t.title, t.created_by, t.created_at,
                   COUNT(m.id) AS msg_count,
                   MAX(m.created_at) AS last_at
            FROM chat_threads t
            LEFT JOIN staff_chat m ON m.thread_id = t.id
            GROUP BY t.id
            ORDER BY COALESCE(MAX(m.created_at), t.created_at) DESC
        """)
    con.close()
    return jsonify([{**dict(r), "created_at": str(r["created_at"])[:16], "last_at": str(r["last_at"] or r["created_at"])[:16]} for r in rows])


@admin_bp.route("/api/chat_threads", methods=["POST"])
def api_chat_threads_post():
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    title = (body.get("title") or "").strip()
    created_by = (body.get("created_by") or "匿名").strip()
    first_message = (body.get("first_message") or "").strip()
    if not title:
        return jsonify({"error": "タイトルを入力してください"}), 400
    con = get_con()
    if USE_PG:
        cur = execute(con, "INSERT INTO chat_threads (title, created_by) VALUES (?, ?) RETURNING id", (title, created_by))
        thread_id = cur.fetchone()[0]
    else:
        cur = execute(con, "INSERT INTO chat_threads (title, created_by) VALUES (?, ?)", (title, created_by))
        thread_id = cur.lastrowid
    if first_message:
        execute(con, "INSERT INTO staff_chat (sender, message, image_data, thread_id) VALUES (?, ?, '', ?)", (created_by, first_message, thread_id))
    con.commit(); con.close()
    return jsonify({"ok": True, "thread_id": thread_id})


@admin_bp.route("/api/chat_threads/<int:thread_id>", methods=["DELETE"])
def api_chat_threads_delete(thread_id):
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM staff_chat WHERE thread_id=?", (thread_id,))
    execute(con, "DELETE FROM chat_threads WHERE id=?", (thread_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/backup-status")
def api_backup_status():
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    import urllib.request, json as _json
    try:
        repo = "Qiuqiu533/Proud-library"
        url = f"https://api.github.com/repos/{repo}/actions/workflows/backup.yml/runs?per_page=1&status=success"
        req = urllib.request.Request(url, headers={"User-Agent": "proud-library"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _json.loads(r.read())
        runs = data.get("workflow_runs", [])
        if runs:
            ts = runs[0].get("updated_at", "")[:10]
            return jsonify({"last_backup": ts})
    except Exception:
        pass
    return jsonify({"last_backup": None})


@admin_bp.route("/api/admin/sync-catalog-now", methods=["POST"])
def api_sync_catalog_now():
    """新刊の蔵書ジャンル分類（genre_books同期）を管理者が即時実行する。
    通常は週1回のバックグラウンド更新のみだが、新刊追加直後に検索できない
    という声を受けて手動トリガーを追加した（2026-07-05）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.books import _auto_classify_new_books, is_genre_classify_running
    if is_genre_classify_running():
        return jsonify({"status": "already_running"}), 409
    _auto_classify_new_books(force=True)
    return jsonify({"status": "started"})


@admin_bp.route("/api/admin/sync-catalog-status")
def api_sync_catalog_status():
    """蔵書同期の実行中フラグと最終実行時刻を返す（管理画面のポーリング用）"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.books import is_genre_classify_running
    return jsonify({
        "running": is_genre_classify_running(),
        "last_update": get_setting("genre_last_update", ""),
    })


@admin_bp.route("/api/admin/integrity-audit/start", methods=["POST"])
def api_integrity_audit_start():
    """genre_books全件をOpenBDと突き合わせ、ISBN不一致（誤ったタイトル・著者が
    登録されているケース）を検出する。自動修復はせず、検出のみ行う
    （2026-07-05: ISBN 9784488029364の誤登録事故を受けて追加）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.integrity import run_integrity_audit, is_audit_running
    if is_audit_running():
        return jsonify({"status": "already_running"}), 409
    body = request.get_json(silent=True) or {}
    limit = body.get("limit")
    run_integrity_audit(force=True, limit=limit)
    return jsonify({"status": "started"})


@admin_bp.route("/api/admin/integrity-audit/status")
def api_integrity_audit_status():
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.integrity import is_audit_running
    con = get_con()
    row = fetchone(con, "SELECT COUNT(*) as cnt FROM integrity_findings WHERE resolved=%s" if USE_PG
                    else "SELECT COUNT(*) as cnt FROM integrity_findings WHERE resolved=0", (False,) if USE_PG else ())
    con.close()
    return jsonify({"running": is_audit_running(), "unresolved_count": row["cnt"] if row else 0})


@admin_bp.route("/api/admin/integrity-audit/findings")
def api_integrity_audit_findings():
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    rows = fetchall(con, "SELECT * FROM integrity_findings WHERE resolved=%s ORDER BY checked_at DESC LIMIT 200" if USE_PG
                     else "SELECT * FROM integrity_findings WHERE resolved=0 ORDER BY checked_at DESC LIMIT 200",
                     (False,) if USE_PG else ())
    con.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/api/admin/integrity-audit/repair", methods=["POST"])
def api_integrity_audit_repair():
    """管理者が承認したフィールドのみOpenBDの値で上書きする。自動実行はしない。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    isbn = (body.get("isbn") or "").strip()
    fields = body.get("fields") or []
    operator = (body.get("operator") or "").strip() or "不明"
    if not isbn or not fields:
        return jsonify({"error": "isbn and fields are required"}), 400
    from services.integrity import repair_finding
    result, code = repair_finding(isbn, fields, operator)
    return jsonify(result), code

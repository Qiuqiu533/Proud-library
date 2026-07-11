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
    """未解決の検出結果を、修復優先度スコアの高い順（タイトル・著者とも不一致
    ＝本物の異常の可能性が高いものを最優先）に返す（2026-07-06）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.integrity import severity_info
    con = get_con()
    rows = fetchall(con, "SELECT * FROM integrity_findings WHERE resolved=%s ORDER BY checked_at DESC LIMIT 500" if USE_PG
                     else "SELECT * FROM integrity_findings WHERE resolved=0 ORDER BY checked_at DESC LIMIT 500",
                     (False,) if USE_PG else ())
    con.close()
    result = []
    for r in rows:
        d = dict(r)
        d.update(severity_info(d.get("mismatch_fields", "")))
        result.append(d)
    result.sort(key=lambda d: d["score"], reverse=True)
    return jsonify(result[:200])


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


@admin_bp.route("/api/admin/integrity-audit/bulk-repair", methods=["POST"])
def api_integrity_audit_bulk_repair():
    """指定した重要度（通常はcritical）の未解決findingsを一括修復する。
    ランダムサンプル検証で精度がほぼ100%と確認できたcriticalカテゴリのみを
    想定した運用向け機能（2026-07-07追加）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    level = (body.get("level") or "critical").strip()
    operator = (body.get("operator") or "").strip() or "不明"
    if level not in ("critical", "warning", "info"):
        return jsonify({"error": "invalid level"}), 400
    from services.integrity import bulk_repair_by_level, is_bulk_repair_running
    if is_bulk_repair_running():
        return jsonify({"status": "already_running"}), 409
    result, code = bulk_repair_by_level(level, operator)
    return jsonify(result), code


@admin_bp.route("/api/admin/integrity-audit/bulk-repair-status")
def api_integrity_audit_bulk_repair_status():
    """一括修復の実行中フラグと直近の結果を返す（ポーリング用）"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.integrity import is_bulk_repair_running, get_bulk_repair_last_result
    return jsonify({"running": is_bulk_repair_running(), "last_result": get_bulk_repair_last_result()})


@admin_bp.route("/api/admin/integrity-audit/backfill-ai-clear", methods=["POST"])
def api_integrity_audit_backfill_ai_clear():
    """title/authorが過去に修復された本のうち、旧書誌情報のままのAI書評・説明文を
    一括クリアする（2026-07-07: repair_finding修正前の修復分向けの一回限りの遡及処理）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    operator = (body.get("operator") or "").strip() or "不明"
    from services.integrity import backfill_clear_stale_ai_reviews
    result, code = backfill_clear_stale_ai_reviews(operator)
    return jsonify(result), code


@admin_bp.route("/api/admin/integrity-audit/backfill-ai-clear-status")
def api_integrity_audit_backfill_ai_clear_status():
    """AI書評遡及クリアの実行中フラグと直近の結果を返す（ポーリング用）"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.integrity import is_backfill_ai_clear_running, get_backfill_ai_clear_last_result
    return jsonify({"running": is_backfill_ai_clear_running(), "last_result": get_backfill_ai_clear_last_result()})


@admin_bp.route("/api/admin/integrity-audit/dashboard")
def api_integrity_audit_dashboard():
    """データ健全性ダッシュボード用の集計値を返す。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.integrity import dashboard_summary
    return jsonify(dashboard_summary())


@admin_bp.route("/api/admin/ai-review/estimate")
def api_ai_review_estimate():
    """未生成のAI書評の対象件数と概算コストを返す（OpenAI APIは呼ばない）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    limit = request.args.get("limit", 100, type=int)
    from services.ai_review_generator import estimate_regeneration
    return jsonify(estimate_regeneration(limit))


@admin_bp.route("/api/admin/ai-review/regenerate", methods=["POST"])
def api_ai_review_regenerate():
    """AI書評の半自動再生成を開始する（Phase 1: 手動起動・1ジョブ最大100件）。"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    limit = body.get("limit", 100)
    operator = (body.get("operator") or "").strip() or "不明"
    isbn = (body.get("isbn") or "").strip()
    isbns = body.get("isbns") or []
    from services.ai_review_generator import start_regeneration
    result, code = start_regeneration(limit, operator, isbn, isbns)
    return jsonify(result), code


@admin_bp.route("/api/admin/ai-review/regenerate-status")
def api_ai_review_regenerate_status():
    """AI書評再生成の実行中フラグと直近の結果を返す（ポーリング用）"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401
    from services.ai_review_generator import is_regeneration_running, get_regeneration_last_result
    return jsonify({"running": is_regeneration_running(), "last_result": get_regeneration_last_result()})

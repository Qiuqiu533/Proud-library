from flask import Blueprint, request, jsonify
from config import get_board_password
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.audit import log_action
from services.utils import rate_limit

events_bp = Blueprint("events", __name__)


def _board_auth():
    return request.headers.get("X-Password") == get_board_password()


def _resident_auth(body: dict):
    """room + password で住民認証。成功時 room を返す。"""
    from services.utils import _verify_password, _is_bcrypt_hash
    room     = (body.get("room")     or "").strip()
    password = (body.get("password") or "").strip()
    if not room or not password:
        return None
    ph = "%s" if USE_PG else "?"
    con = get_con()
    user = fetchone(con, f"SELECT password_hash, password_salt, pin FROM user_accounts WHERE room={ph}", (room,))
    con.close()
    if not user:
        return None
    ph   = user.get("password_hash", "")
    salt = user.get("password_salt", "")
    if ph:
        return room if _verify_password(password, ph, salt) else None
    return room if user.get("pin") == password else None


def _entry_count(con, event_id: int) -> tuple[int, int]:
    """(confirmed_count, waitlist_count) を返す"""
    ph = "%s" if USE_PG else "?"
    if USE_PG:
        r1 = fetchone(con, f"SELECT COUNT(*) AS c FROM event_entries WHERE event_id={ph} AND is_waitlist=FALSE", (event_id,))
        r2 = fetchone(con, f"SELECT COUNT(*) AS c FROM event_entries WHERE event_id={ph} AND is_waitlist=TRUE",  (event_id,))
    else:
        r1 = fetchone(con, f"SELECT COUNT(*) AS c FROM event_entries WHERE event_id={ph} AND is_waitlist=0", (event_id,))
        r2 = fetchone(con, f"SELECT COUNT(*) AS c FROM event_entries WHERE event_id={ph} AND is_waitlist=1", (event_id,))
    return (r1["c"] if r1 else 0), (r2["c"] if r2 else 0)


# ── 公開エンドポイント ────────────────────────────────────────────────────

@events_bp.route("/api/events")
def api_events_list():
    """公開イベント一覧（status=open のもの、締切前優先）"""
    con = get_con()
    try:
        rows = fetchall(con, """
            SELECT id, title, description, event_date, event_time, location,
                   capacity, entry_deadline, status, created_at
            FROM events
            WHERE status != 'hidden'
            ORDER BY event_date ASC
        """)
        result = []
        for r in rows:
            confirmed, waitlist = _entry_count(con, r["id"])
            result.append({
                **{k: r[k] for k in r.keys()},
                "confirmed": confirmed,
                "waitlist":  waitlist,
                "created_at": str(r["created_at"])[:10],
            })
        con.close()
        return jsonify(result)
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/events/<int:event_id>")
def api_event_detail(event_id):
    """イベント詳細 + 自分の申込状況（?room=&password=）"""
    room     = request.args.get("room", "").strip()
    password = request.args.get("password", "").strip()
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        r = fetchone(con, f"SELECT * FROM events WHERE id={ph}", (event_id,))
        if not r:
            con.close()
            return jsonify({"error": "not found"}), 404
        confirmed, waitlist = _entry_count(con, event_id)
        my_entry = None
        if room:
            my_entry = fetchone(con,
                f"SELECT is_waitlist, created_at FROM event_entries WHERE event_id={ph} AND room={ph}",
                (event_id, room))
        con.close()
        return jsonify({
            **{k: r[k] for k in r.keys()},
            "confirmed": confirmed,
            "waitlist":  waitlist,
            "my_status": ("waitlist" if my_entry and my_entry["is_waitlist"] else
                          "confirmed" if my_entry else None),
        })
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


# ── 申込・キャンセル（住民） ────────────────────────────────────────────

@events_bp.route("/api/events/<int:event_id>/entry", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_event_entry(event_id):
    """イベント申込。定員超の場合はキャンセル待ちに自動登録。"""
    body = request.get_json() or {}
    room = _resident_auth(body)
    if not room:
        return jsonify({"error": "unauthorized"}), 401
    name = (body.get("name") or "").strip()[:50]
    note = (body.get("note") or "").strip()[:200]
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        ev = fetchone(con, f"SELECT * FROM events WHERE id={ph}", (event_id,))
        if not ev:
            con.close()
            return jsonify({"error": "イベントが見つかりません"}), 404
        if ev["status"] == "closed":
            con.close()
            return jsonify({"error": "申込受付を終了しました"}), 400
        if ev["entry_deadline"] and ev["entry_deadline"] < __import__("datetime").date.today().isoformat():
            con.close()
            return jsonify({"error": "申込締切を過ぎています"}), 400
        # 既に申込済み？
        existing = fetchone(con,
            f"SELECT id, is_waitlist FROM event_entries WHERE event_id={ph} AND room={ph}",
            (event_id, room))
        if existing:
            con.close()
            return jsonify({"error": "すでに申込済みです",
                            "status": "waitlist" if existing["is_waitlist"] else "confirmed"}), 409
        confirmed, _ = _entry_count(con, event_id)
        capacity = ev["capacity"] or 0
        is_waitlist = capacity > 0 and confirmed >= capacity
        wl_val = is_waitlist if USE_PG else (1 if is_waitlist else 0)
        if USE_PG:
            execute(con,
                "INSERT INTO event_entries (event_id, room, name, note, is_waitlist) VALUES (%s,%s,%s,%s,%s)",
                (event_id, room, name, note, wl_val))
        else:
            execute(con,
                "INSERT INTO event_entries (event_id, room, name, note, is_waitlist) VALUES (?,?,?,?,?)",
                (event_id, room, name, note, wl_val))
        con.commit()
        con.close()
        status = "waitlist" if is_waitlist else "confirmed"
        log_action("イベント申込", ev["title"], f"room={room} status={status}")
        return jsonify({"ok": True, "status": status})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/events/<int:event_id>/entry", methods=["DELETE"])
def api_event_cancel(event_id):
    """申込キャンセル。キャンセル後、キャンセル待ち1番目を自動繰り上げ。"""
    body = request.get_json() or {}
    room = _resident_auth(body)
    if not room:
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        entry = fetchone(con,
            f"SELECT id, is_waitlist FROM event_entries WHERE event_id={ph} AND room={ph}",
            (event_id, room))
        if not entry:
            con.close()
            return jsonify({"error": "申込が見つかりません"}), 404
        was_confirmed = not entry["is_waitlist"]
        execute(con, f"DELETE FROM event_entries WHERE event_id={ph} AND room={ph}", (event_id, room))
        # 確定枠キャンセルの場合: キャンセル待ち1番目を繰り上げ
        if was_confirmed:
            if USE_PG:
                first_wait = fetchone(con,
                    "SELECT id FROM event_entries WHERE event_id=%s AND is_waitlist=TRUE ORDER BY id ASC LIMIT 1",
                    (event_id,))
                if first_wait:
                    execute(con,
                        "UPDATE event_entries SET is_waitlist=FALSE WHERE id=%s",
                        (first_wait["id"],))
            else:
                first_wait = fetchone(con,
                    "SELECT id FROM event_entries WHERE event_id=? AND is_waitlist=1 ORDER BY id ASC LIMIT 1",
                    (event_id,))
                if first_wait:
                    execute(con, "UPDATE event_entries SET is_waitlist=0 WHERE id=?", (first_wait["id"],))
        con.commit()
        con.close()
        ev = fetchone(get_con(), f"SELECT title FROM events WHERE id={ph}", (event_id,))
        log_action("イベントキャンセル", ev["title"] if ev else str(event_id), f"room={room}")
        return jsonify({"ok": True, "promoted": was_confirmed and bool(first_wait if was_confirmed else None)})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


# ── 管理者エンドポイント ────────────────────────────────────────────────

@events_bp.route("/api/admin/events", methods=["GET"])
def api_admin_events():
    """全イベント一覧（管理者）"""
    if not _board_auth():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        rows = fetchall(con, "SELECT * FROM events ORDER BY event_date ASC")
        result = []
        for r in rows:
            confirmed, waitlist = _entry_count(con, r["id"])
            result.append({**{k: r[k] for k in r.keys()},
                           "confirmed": confirmed, "waitlist": waitlist,
                           "created_at": str(r["created_at"])[:10]})
        con.close()
        return jsonify(result)
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/admin/events", methods=["POST"])
def api_admin_create_event():
    """イベント作成（管理者）。image_dataがあればannouncementsにも自動投稿。"""
    if not _board_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    title       = (body.get("title")       or "").strip()
    if not title:
        return jsonify({"error": "タイトルは必須です"}), 400
    description = (body.get("description") or "").strip()
    event_date  = (body.get("event_date")  or "").strip()
    event_time  = (body.get("event_time")  or "").strip()
    location    = (body.get("location")    or "").strip()
    capacity    = int(body.get("capacity") or 0)
    deadline    = (body.get("entry_deadline") or "").strip() or None
    status      = (body.get("status") or "open")
    image_data  = (body.get("image_data")  or "").strip()
    post_news   = body.get("post_news", True)  # お知らせ自動投稿フラグ

    ph = "%s" if USE_PG else "?"
    con = get_con()
    try:
        execute(con, f"""
            INSERT INTO events (title, description, event_date, event_time, location, capacity, entry_deadline, status, image_data)
            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        """, (title, description, event_date, event_time, location, capacity, deadline, status, image_data))

        # お知らせに自動投稿
        if post_news:
            news_body = description or ""
            if event_date:
                time_str = f" {event_time}" if event_time else ""
                news_body = f"📅 {event_date}{time_str}" + (f"\n📍 {location}" if location else "") + (f"\n\n{description}" if description else "")
            execute(con, f"""
                INSERT INTO announcements (title, body, category, image_url, event_date)
                VALUES ({ph},{ph},{ph},{ph},{ph})
            """, (title, news_body, "イベント", image_data, event_date or None))

        con.commit()
        con.close()
        log_action("イベント作成", title)
        return jsonify({"ok": True})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/admin/events/<int:event_id>", methods=["PATCH"])
def api_admin_update_event(event_id):
    """イベント更新（管理者）"""
    if not _board_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    fields = ["title", "description", "event_date", "event_time", "location",
              "capacity", "entry_deadline", "status"]
    updates = {k: body[k] for k in fields if k in body}
    if not updates:
        return jsonify({"error": "更新項目がありません"}), 400
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        for k, v in updates.items():
            execute(con, f"UPDATE events SET {k}={ph} WHERE id={ph}", (v, event_id))
        con.commit()
        con.close()
        log_action("イベント更新", f"id={event_id}", str(list(updates.keys())))
        return jsonify({"ok": True})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/admin/events/<int:event_id>", methods=["DELETE"])
def api_admin_delete_event(event_id):
    """イベント削除（管理者）"""
    if not _board_auth():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        ev = fetchone(con, f"SELECT title FROM events WHERE id={ph}", (event_id,))
        execute(con, f"DELETE FROM events WHERE id={ph}", (event_id,))
        con.commit()
        con.close()
        log_action("イベント削除", ev["title"] if ev else str(event_id))
        return jsonify({"ok": True})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/admin/events/<int:event_id>/entries")
def api_admin_event_entries(event_id):
    """参加者一覧（管理者）"""
    if not _board_auth():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        rows = fetchall(con,
            f"SELECT id, room, name, note, is_waitlist, created_at FROM event_entries WHERE event_id={ph} ORDER BY id ASC",
            (event_id,))
        con.close()
        return jsonify([{
            "id": r["id"], "room": r["room"], "name": r["name"] or "",
            "note": r["note"] or "",
            "is_waitlist": bool(r["is_waitlist"]),
            "created_at": str(r["created_at"])[:16],
        } for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@events_bp.route("/api/admin/events/<int:event_id>/entries/<int:entry_id>", methods=["DELETE"])
def api_admin_remove_entry(event_id, entry_id):
    """参加者を管理者が削除（キャンセル待ち繰り上げあり）"""
    if not _board_auth():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        entry = fetchone(con, f"SELECT room, is_waitlist FROM event_entries WHERE id={ph}", (entry_id,))
        if not entry:
            con.close()
            return jsonify({"error": "not found"}), 404
        was_confirmed = not entry["is_waitlist"]
        execute(con, f"DELETE FROM event_entries WHERE id={ph}", (entry_id,))
        if was_confirmed:
            if USE_PG:
                first_wait = fetchone(con,
                    "SELECT id FROM event_entries WHERE event_id=%s AND is_waitlist=TRUE ORDER BY id ASC LIMIT 1",
                    (event_id,))
                if first_wait:
                    execute(con, "UPDATE event_entries SET is_waitlist=FALSE WHERE id=%s", (first_wait["id"],))
            else:
                first_wait = fetchone(con,
                    "SELECT id FROM event_entries WHERE event_id=? AND is_waitlist=1 ORDER BY id ASC LIMIT 1",
                    (event_id,))
                if first_wait:
                    execute(con, "UPDATE event_entries SET is_waitlist=0 WHERE id=?", (first_wait["id"],))
        con.commit()
        con.close()
        log_action("参加者削除（管理者）", f"event={event_id}", f"room={entry['room']}")
        return jsonify({"ok": True})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify
from config import get_board_password, LIBRARYLIFE_BASE, LIBRARY_INFO, check_password
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.utils import _hash_password

loans_bp = Blueprint("loans", __name__)


def _csv_safe(value):
    """Excel等でのCSVインジェクション対策。=+-@ で始まる値は先頭にシングルクォートを付与して無害化する。"""
    s = str(value) if value is not None else ""
    if s and s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s


@loans_bp.route("/api/library-info")
def api_library_info():
    return jsonify(LIBRARY_INFO)


@loans_bp.route("/api/library-card-info")
def api_library_card_info():
    """librarylife.netの会員証URLから会員IDを取得"""
    url = request.args.get("url", "").strip()
    if not url or "librarylife.net/card/" not in url:
        return jsonify({"error": "librarylife.netの会員証URLを入力してください"}), 400
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        member_id = ""
        for el in soup.find_all(text=True):
            t = el.strip()
            if "会員ID" in t or "会員番号" in t or "Member" in t:
                parent = el.parent
                nxt = parent.find_next_sibling()
                if nxt and nxt.text.strip().isdigit():
                    member_id = nxt.text.strip()
                    break
                import re
                m = re.search(r'\d{7,12}', t)
                if m:
                    member_id = m.group()
                    break
        if not member_id:
            import re
            text = soup.get_text()
            m = re.search(r'(?<!\d)(\d{10})(?!\d)', text)
            if m:
                member_id = m.group(1)
        barcode_url = ""
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "barcode" in src.lower() or "bar" in src.lower():
                barcode_url = src if src.startswith("http") else LIBRARYLIFE_BASE + src
                break
        if not member_id and not barcode_url:
            return jsonify({"error": "会員IDが見つかりませんでした。IDを直接入力してください"}), 404
        return jsonify({"member_id": member_id, "barcode_url": barcode_url})
    except Exception as e:
        return jsonify({"error": "読み込みに失敗しました。IDを直接入力してください"}), 500


@loans_bp.route("/api/availability/cached")
def api_availability_cached():
    """キャッシュ済みの在架状況を一括返却（スクレイピングなし）"""
    isbns_param = request.args.get("isbns", "")
    isbns = [i.strip() for i in isbns_param.split(",") if i.strip()]
    if not isbns:
        return jsonify({})
    con = get_con()
    try:
        placeholders = ",".join(["%s" if USE_PG else "?" for _ in isbns])
        rows = fetchall(con, f"SELECT isbn, status FROM availability_cache WHERE isbn IN ({placeholders})", tuple(isbns))
        con.close()
        return jsonify({r["isbn"]: r["status"] for r in rows})
    except Exception:
        con.close()
        return jsonify({})


@loans_bp.route("/api/availability/<isbn>")
def api_availability(isbn):
    """本の在架状況のみを高速取得（2時間以内のキャッシュがあればそれを返す）"""
    con = get_con()
    try:
        if USE_PG:
            cached = fetchone(con, "SELECT status, updated_at FROM availability_cache WHERE isbn=%s AND updated_at > NOW() - INTERVAL '2 hours'", (isbn,))
        else:
            cached = fetchone(con, "SELECT status, updated_at FROM availability_cache WHERE isbn=? AND updated_at > datetime('now','-2 hours','localtime')", (isbn,))
        if cached:
            con.close()
            return jsonify({"status": cached["status"], "cached": True})
    except Exception:
        pass

    try:
        url = f"{LIBRARYLIFE_BASE}/booksearch/detail/{isbn}"
        resp = requests.get(url, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        availability = []
        for row in soup.select("table.table tbody tr"):
            tds = row.find_all("td")
            if len(tds) >= 3 and tds[1].text.strip() and tds[2].text.strip():
                availability.append({"library": tds[1].text.strip(), "status": tds[2].text.strip()})
        if not availability:
            try:
                book_row = fetchone(con, "SELECT title, author FROM genre_books WHERE isbn=?", (isbn,))
                title = book_row["title"] if book_row else ""
                author = book_row["author"] if book_row else ""
                if USE_PG:
                    execute(con, """
                        INSERT INTO availability_cache (isbn, status, title, author, updated_at)
                        VALUES (%s, 'unknown', %s, %s, NOW() - INTERVAL '90 minutes')
                        ON CONFLICT (isbn) DO UPDATE SET status='unknown', updated_at=NOW() - INTERVAL '90 minutes'
                    """, (isbn, title, author))
                else:
                    execute(con, """
                        INSERT OR REPLACE INTO availability_cache (isbn, status, title, author, updated_at)
                        VALUES (?, 'unknown', ?, ?, datetime('now','-90 minutes','localtime'))
                    """, (isbn, title, author))
                con.commit()
            except Exception:
                pass
            con.close()
            return jsonify({"status": "unknown"})
        statuses = [a["status"] for a in availability]
        AVAILABLE_WORDS = ("利用可能", "在架", "貸出可", "館内のみ", "開架", "配架中")
        LOANED_WORDS = ("貸出中", "貸出", "予約中", "返却待ち", "禁帯出")
        if any(any(w in s for w in AVAILABLE_WORDS) for s in statuses):
            result_status = "available"
        elif any(any(w in s for w in LOANED_WORDS) for s in statuses):
            result_status = "loaned"
        else:
            result_status = "unknown"

        try:
            book_row = fetchone(con, "SELECT title, author FROM genre_books WHERE isbn=?", (isbn,))
            title = book_row["title"] if book_row else ""
            author = book_row["author"] if book_row else ""
            if USE_PG:
                execute(con, """
                    INSERT INTO availability_cache (isbn, status, title, author, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (isbn) DO UPDATE SET status=EXCLUDED.status, title=EXCLUDED.title, author=EXCLUDED.author, updated_at=NOW()
                """, (isbn, result_status, title, author))
                # 貸出状況が確定した場合は loan_history に記録
                if result_status in ("loaned", "available"):
                    try:
                        execute(con, """
                            INSERT INTO loan_history (isbn, status, title, author, recorded_at)
                            VALUES (%s, %s, %s, %s, NOW())
                        """, (isbn, result_status, title, author))
                    except Exception:
                        pass
            else:
                execute(con, """
                    INSERT OR REPLACE INTO availability_cache (isbn, status, title, author, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now','localtime'))
                """, (isbn, result_status, title, author))
                if result_status in ("loaned", "available"):
                    try:
                        execute(con, """
                            INSERT INTO loan_history (isbn, status, title, author, recorded_at)
                            VALUES (?, ?, ?, ?, datetime('now','localtime'))
                        """, (isbn, result_status, title, author))
                    except Exception:
                        pass
            con.commit()
        except Exception:
            pass

        con.close()
        return jsonify({"status": result_status, "items": availability})
    except Exception:
        con.close()
        return jsonify({"status": "error"}), 500


@loans_bp.route("/api/availability/loaned")
def api_availability_loaned():
    """貸出中としてキャッシュされた書籍一覧（最新48時間）"""
    con = get_con()
    try:
        if USE_PG:
            rows = fetchall(con, """
                SELECT isbn, title, author, updated_at FROM availability_cache
                WHERE status='loaned' AND updated_at > NOW() - INTERVAL '48 hours'
                ORDER BY updated_at DESC
            """)
        else:
            rows = fetchall(con, """
                SELECT isbn, title, author, updated_at FROM availability_cache
                WHERE status='loaned' AND updated_at > datetime('now','-48 hours','localtime')
                ORDER BY updated_at DESC
            """)
        con.close()
        return jsonify(rows)
    except Exception as e:
        con.close()
        return jsonify([]), 500


@loans_bp.route("/api/admin/availability-stale")
def api_availability_stale():
    """24時間以上更新されていない書籍ISBNを最大N件返す（フロント側で順次チェックに使用）"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    limit = min(int(request.args.get("limit", 30)), 100)
    con = get_con()
    try:
        if USE_PG:
            rows = fetchall(con, """
                SELECT g.isbn, g.title, a.updated_at FROM genre_books g
                LEFT JOIN availability_cache a ON a.isbn = g.isbn
                WHERE a.isbn IS NULL OR a.updated_at < NOW() - INTERVAL '24 hours'
                ORDER BY a.updated_at ASC NULLS FIRST
                LIMIT %s
            """, (limit,))
        else:
            rows = fetchall(con, """
                SELECT g.isbn, g.title, a.updated_at FROM genre_books g
                LEFT JOIN availability_cache a ON a.isbn = g.isbn
                WHERE a.isbn IS NULL OR a.updated_at < datetime('now','-24 hours','localtime')
                ORDER BY a.updated_at ASC
                LIMIT ?
            """, (limit,))
        con.close()
        return jsonify([{"isbn": r["isbn"], "title": r["title"] or r["isbn"]} for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/dashboard-data")
def api_admin_dashboard_data():
    """ダッシュボード用データを1リクエストで返す"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        reqs = fetchall(con, "SELECT id,type,status,title,reason,room,votes,created_at,reply FROM book_requests ORDER BY id DESC") or []
        issues = fetchall(con, "SELECT id,title,status,sort_order FROM issues ORDER BY sort_order ASC, id ASC") or []
        new_count_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM new_arrivals")
        new_count = new_count_row["cnt"] if new_count_row else 0
        total_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM genre_books")
        total_books = total_row["cnt"] if total_row else 0
        sched = fetchall(con, "SELECT id,event_date,title,type FROM lib_schedule ORDER BY event_date ASC") or []
        db_total_mb = None
        if USE_PG:
            size_row = fetchone(con, "SELECT ROUND(pg_database_size(current_database()) / 1024.0 / 1024.0, 1) AS mb")
            if size_row:
                db_total_mb = float(size_row["mb"])
        con.close()
        return jsonify({
            "requests": [dict(r) for r in reqs],
            "issues": [dict(i) for i in issues],
            "new_arrivals_count": new_count,
            "total_books": total_books,
            "schedule": [dict(s) for s in sched],
            "db_total_mb": db_total_mb,
        })
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


_EXPECTED_TABLES = [
    "ratings", "announcements", "issues", "book_requests", "calendar_events",
    "settings", "collections", "user_accounts", "password_reset_tokens",
    "genre_books", "new_arrivals", "availability_cache", "staff_chat",
    "chat_threads", "admin_users", "award_books", "applied_migrations",
    "wish_list", "invite_codes", "audit_log", "events", "event_entries",
    "reading_timeline", "newsletters", "plam_coverage_log", "plam_fix_log",
    "loan_history", "my_loans",
]


@loans_bp.route("/api/admin/migration-status")
def api_migration_status():
    """マイグレーション適用状況・主要テーブルの存在確認（管理者向け診断）"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        applied = fetchall(con, "SELECT name, applied_at FROM applied_migrations ORDER BY applied_at DESC")
        applied_list = [{"name": r["name"], "applied_at": str(r["applied_at"])} for r in applied]

        if USE_PG:
            existing_rows = fetchall(con, """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='public'
            """)
            existing = {r["table_name"] for r in existing_rows}
        else:
            existing_rows = fetchall(con, "SELECT name FROM sqlite_master WHERE type='table'")
            existing = {r["name"] for r in existing_rows}

        tables = [{"name": t, "exists": t in existing} for t in _EXPECTED_TABLES]
        missing = [t["name"] for t in tables if not t["exists"]]
        con.close()
        return jsonify({
            "applied_migrations_count": len(applied_list),
            "applied_migrations": applied_list,
            "tables": tables,
            "missing_tables": missing,
        })
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/db-size")
def api_db_size():
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        if USE_PG:
            size_row = fetchone(con, "SELECT pg_database_size(current_database()) AS bytes")
            total_bytes = size_row["bytes"]
            rows = fetchall(con, """
                SELECT relname AS name,
                       pg_total_relation_size(relid) AS bytes
                FROM pg_catalog.pg_statio_user_tables
                ORDER BY bytes DESC
            """)
            tables = [{"name": r["name"], "mb": round(r["bytes"]/1024/1024, 2)} for r in rows]
        else:
            import os as _os
            total_bytes = _os.path.getsize("data.db")
            tables = []
        con.close()
        limit_bytes = 512 * 1024 * 1024
        return jsonify({
            "total_mb": round(total_bytes / 1024 / 1024, 2),
            "limit_mb": 512,
            "percent": round(total_bytes / limit_bytes * 100, 1),
            "tables": tables
        })
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/members")
def api_admin_members():
    """会員一覧（管理者）"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    ph = "%s" if USE_PG else "?"
    con = get_con()
    try:
        if USE_PG:
            rows = fetchall(con, "SELECT room, email, created_at FROM user_accounts ORDER BY created_at DESC")
        else:
            rows = fetchall(con, "SELECT room, email, updated_at AS created_at FROM user_accounts ORDER BY updated_at DESC")
        con.close()
        return jsonify([{
            "room": r["room"],
            "email": r["email"] or "",
            "created_at": str(r.get("created_at") or "")[:10],
        } for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/requests-csv")
def api_requests_csv():
    """リクエスト・ご要望一覧をCSVでダウンロード（管理者用）"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        rows = fetchall(con, "SELECT id,type,title,author,reason,room,status,votes,created_at,reply FROM book_requests ORDER BY id DESC")
        con.close()
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID","種別","タイトル","著者","理由","部屋","ステータス","賛同数","登録日","返信"])
        for r in rows:
            w.writerow([r["id"], _csv_safe(r["type"]), _csv_safe(r["title"]), _csv_safe(r["author"]), _csv_safe(r["reason"]),
                        _csv_safe(r["room"]), _csv_safe(r["status"]), r["votes"], str(r["created_at"])[:10], _csv_safe(r["reply"])])
        from flask import Response
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=requests.csv"})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/books-csv")
def api_books_csv():
    """蔵書一覧をCSVでダウンロード（棚卸し用）"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        rows = fetchall(con, "SELECT isbn, title, author, publisher, genre FROM genre_books ORDER BY genre, title")
        con.close()
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ISBN","タイトル","著者","出版社","ジャンル"])
        for r in rows:
            w.writerow([r["isbn"], _csv_safe(r["title"]), _csv_safe(r["author"]), _csv_safe(r["publisher"]), _csv_safe(r["genre"])])
        from flask import Response
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=books.csv"})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/ops-stats")
def api_ops_stats():
    """運営統計: 貸出状況・評価・リクエスト対応サマリ"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        loaned_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM availability_cache WHERE status='loaned'")
        loaned = loaned_row["cnt"] if loaned_row else 0

        genre_rows = fetchall(con, "SELECT genre, COUNT(*) AS cnt FROM genre_books GROUP BY genre ORDER BY cnt DESC LIMIT 10")
        total_books_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM genre_books")
        total_books = total_books_row["cnt"] if total_books_row else 0

        wish_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM wish_list")
        total_wishes = wish_row["cnt"] if wish_row else 0

        rating_row = fetchone(con, "SELECT COUNT(*) AS rated, SUM(votes) AS total_votes FROM ratings WHERE votes > 0")
        top_rated = fetchall(con, """
            SELECT r.isbn, g.title, r.score, r.votes
            FROM ratings r LEFT JOIN genre_books g ON r.isbn = g.isbn
            WHERE r.votes >= 2
            ORDER BY r.score DESC, r.votes DESC LIMIT 5
        """)

        req_total_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM book_requests WHERE type='request'")
        req_done_row  = fetchone(con, "SELECT COUNT(*) AS cnt FROM book_requests WHERE type='request' AND status IN ('done','approved')")
        fb_total_row  = fetchone(con, "SELECT COUNT(*) AS cnt FROM book_requests WHERE type='feedback'")
        fb_done_row   = fetchone(con, "SELECT COUNT(*) AS cnt FROM book_requests WHERE type='feedback' AND status IN ('fb_done','fb_noted','fb_none','fb_rejected')")

        member_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM user_accounts")

        # 人気作家TOP10（評価数合計）
        top_authors = fetchall(con, """
            SELECT g.author, COUNT(DISTINCT g.isbn) AS book_cnt,
                   COALESCE(SUM(r.votes), 0) AS total_votes,
                   ROUND(AVG(CASE WHEN r.votes > 0 THEN r.score END)::numeric, 1) AS avg_score
            FROM genre_books g
            LEFT JOIN ratings r ON r.isbn = g.isbn
            WHERE g.author IS NOT NULL AND g.author != ''
            GROUP BY g.author
            ORDER BY total_votes DESC, book_cnt DESC
            LIMIT 10
        """ if USE_PG else """
            SELECT g.author, COUNT(DISTINCT g.isbn) AS book_cnt,
                   COALESCE(SUM(r.votes), 0) AS total_votes,
                   ROUND(AVG(CASE WHEN r.votes > 0 THEN r.score END), 1) AS avg_score
            FROM genre_books g
            LEFT JOIN ratings r ON r.isbn = g.isbn
            WHERE g.author IS NOT NULL AND g.author != ''
            GROUP BY g.author
            ORDER BY total_votes DESC, book_cnt DESC
            LIMIT 10
        """)

        # 死蔵本（評価なし・180日以上貸出履歴なし）
        try:
            dead_stock = fetchall(con, """
                SELECT g.isbn, g.title, g.author,
                       MAX(lh.recorded_at) AS last_loaned
                FROM genre_books g
                LEFT JOIN ratings r ON r.isbn = g.isbn
                LEFT JOIN loan_history lh ON lh.isbn = g.isbn AND lh.status = 'loaned'
                WHERE (r.votes IS NULL OR r.votes = 0)
                GROUP BY g.isbn, g.title, g.author
                HAVING MAX(lh.recorded_at) IS NULL
                    OR MAX(lh.recorded_at) < NOW() - INTERVAL '180 days'
                ORDER BY MAX(lh.recorded_at) ASC NULLS FIRST
                LIMIT 20
            """ if USE_PG else """
                SELECT g.isbn, g.title, g.author,
                       MAX(lh.recorded_at) AS last_loaned
                FROM genre_books g
                LEFT JOIN ratings r ON r.isbn = g.isbn
                LEFT JOIN loan_history lh ON lh.isbn = g.isbn AND lh.status = 'loaned'
                WHERE (r.votes IS NULL OR r.votes = 0)
                GROUP BY g.isbn, g.title, g.author
                HAVING MAX(lh.recorded_at) IS NULL
                    OR datetime(MAX(lh.recorded_at)) < datetime('now', '-180 days')
                ORDER BY MAX(lh.recorded_at) ASC
                LIMIT 20
            """)
        except Exception:
            dead_stock = []

        # 稼働統計：過去7日間の新規登録・貸出活動推移
        try:
            reg_trend = fetchall(con, """
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM user_accounts
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY DATE(created_at) ORDER BY day
            """ if USE_PG else """
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM user_accounts
                WHERE created_at >= datetime('now', '-7 days')
                GROUP BY DATE(created_at) ORDER BY day
            """)
        except Exception:
            reg_trend = []

        try:
            loan_trend = fetchall(con, """
                SELECT DATE(recorded_at) AS day, COUNT(*) AS cnt
                FROM loan_history
                WHERE recorded_at >= NOW() - INTERVAL '7 days' AND status = 'loaned'
                GROUP BY DATE(recorded_at) ORDER BY day
            """ if USE_PG else """
                SELECT DATE(recorded_at) AS day, COUNT(*) AS cnt
                FROM loan_history
                WHERE recorded_at >= datetime('now', '-7 days') AND status = 'loaned'
                GROUP BY DATE(recorded_at) ORDER BY day
            """)
        except Exception:
            loan_trend = []

        con.close()
        return jsonify({
            "loaned": loaned,
            "total_books": total_books,
            "total_wishes": total_wishes,
            "genres": [{"genre": r["genre"] or "未分類", "cnt": r["cnt"]} for r in genre_rows],
            "rated_books": rating_row["rated"] if rating_row else 0,
            "total_votes": rating_row["total_votes"] if rating_row else 0,
            "top_rated": [{"isbn": r["isbn"], "title": r["title"] or r["isbn"], "score": r["score"], "votes": r["votes"]} for r in top_rated],
            "req_total": req_total_row["cnt"] if req_total_row else 0,
            "req_done":  req_done_row["cnt"]  if req_done_row  else 0,
            "fb_total":  fb_total_row["cnt"]  if fb_total_row  else 0,
            "fb_done":   fb_done_row["cnt"]   if fb_done_row   else 0,
            "members":   member_row["cnt"]    if member_row    else 0,
            "top_authors": [{"author": r["author"], "book_cnt": r["book_cnt"], "total_votes": r["total_votes"], "avg_score": r["avg_score"]} for r in top_authors],
            "dead_stock": [{"isbn": r["isbn"], "title": r["title"] or r["isbn"], "author": r["author"] or "", "last_loaned": str(r["last_loaned"] or "")[:10] if r["last_loaned"] else "貸出記録なし"} for r in dead_stock],
            "reg_trend":  [{"day": str(r["day"])[:10], "cnt": r["cnt"]} for r in reg_trend],
            "loan_trend": [{"day": str(r["day"])[:10], "cnt": r["cnt"]} for r in loan_trend],
        })
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/wishlist-summary")
def api_wishlist_summary():
    """読みたいリスト集計（購入判断用）: 複数人が登録している本を降順で返す"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        rows = fetchall(con, """
            SELECT w.isbn, COUNT(*) AS wish_count, g.title, g.author
            FROM wish_list w
            LEFT JOIN genre_books g ON g.isbn = w.isbn
            GROUP BY w.isbn, g.title, g.author
            ORDER BY wish_count DESC, w.isbn
            LIMIT 30
        """)
        con.close()
        return jsonify([{
            "isbn": r["isbn"],
            "title": r["title"] or r["isbn"],
            "author": r["author"] or "",
            "wish_count": r["wish_count"],
        } for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/reset-user-password", methods=["POST"])
def api_admin_reset_user_password():
    """管理者による住民パスワードリセット"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    room = (body.get("room") or "").strip()
    new_password = (body.get("new_password") or "").strip()
    if not room or not new_password or len(new_password) < 8:
        return jsonify({"error": "部屋番号と8文字以上の新しいパスワードを入力してください"}), 400
    con = get_con()
    try:
        user = fetchone(con, "SELECT room FROM user_accounts WHERE room=?", (room,))
        if not user:
            con.close()
            return jsonify({"error": f"部屋番号 {room} は登録されていません"}), 404
        h, s = _hash_password(new_password)
        if USE_PG:
            execute(con, "UPDATE user_accounts SET password_hash=%s, password_salt=%s, pin=%s, updated_at=NOW() WHERE room=%s",
                    (h, s, new_password, room))
        else:
            execute(con, "UPDATE user_accounts SET password_hash=?, password_salt=?, pin=?, updated_at=datetime('now','localtime') WHERE room=?",
                    (h, s, new_password, room))
        con.commit()
        con.close()
        return jsonify({"ok": True, "room": room})
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


@loans_bp.route("/api/admin/audit-log")
def api_audit_log():
    """管理者操作ログ（最新200件）"""
    if not check_password(request.headers.get("X-Password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        rows = fetchall(con, """
            SELECT id, action, target, detail, ip, created_at
            FROM audit_log
            ORDER BY id DESC
            LIMIT 200
        """)
        con.close()
        return jsonify([{**r, "created_at": str(r["created_at"])[:16]} for r in rows])
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500

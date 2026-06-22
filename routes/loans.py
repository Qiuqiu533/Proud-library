import requests
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify
from config import get_board_password, LIBRARYLIFE_BASE, LIBRARY_INFO
from database import get_con, execute, fetchone, fetchall, USE_PG

loans_bp = Blueprint("loans", __name__)


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
            else:
                execute(con, """
                    INSERT OR REPLACE INTO availability_cache (isbn, status, title, author, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now','localtime'))
                """, (isbn, result_status, title, author))
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


@loans_bp.route("/api/admin/dashboard-data")
def api_admin_dashboard_data():
    """ダッシュボード用データを1リクエストで返す"""
    if request.headers.get("X-Password") != get_board_password():
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


@loans_bp.route("/api/admin/db-size")
def api_db_size():
    if request.headers.get("X-Password") != get_board_password():
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

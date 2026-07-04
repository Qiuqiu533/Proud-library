import concurrent.futures
import requests
from flask import Blueprint, request, jsonify
from config import get_admin_password, get_board_password, OPENBD_API, check_password
from database import get_con, execute, fetchall
from services.books import fetch_books, get_cover_url, isbn13_to_isbn10, get_recent_isbns

new_arrivals_bp = Blueprint("new_arrivals", __name__)


@new_arrivals_bp.route("/api/new-arrivals")
def api_get_new_arrivals():
    con = get_con()
    rows = fetchall(con, "SELECT id,isbn,arrived_at,title,author,publisher,cover FROM new_arrivals ORDER BY arrived_at DESC, id DESC")
    con.close()
    return jsonify([{**r, "arrived_at": str(r["arrived_at"])[:10]} for r in rows])


@new_arrivals_bp.route("/api/new-arrivals", methods=["POST"])
def api_post_new_arrival():
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    isbn = (body.get("isbn") or "").strip().replace("-", "")
    arrived_at = (body.get("arrived_at") or "").strip()
    if not isbn or not arrived_at:
        return jsonify({"error": "ISBN と入荷日は必須です"}), 400
    title = (body.get("title") or "").strip()
    author = (body.get("author") or "").strip()
    publisher = (body.get("publisher") or "").strip()
    cover = (body.get("cover") or "").strip()
    con = get_con()
    execute(con, "INSERT INTO new_arrivals (isbn,arrived_at,title,author,publisher,cover) VALUES (?,?,?,?,?,?)",
            (isbn, arrived_at, title, author, publisher, cover))
    con.commit(); con.close()
    return jsonify({"ok": True})


@new_arrivals_bp.route("/api/new-arrivals/<int:arrival_id>", methods=["DELETE"])
def api_delete_new_arrival(arrival_id):
    body = request.get_json()
    if not check_password(body.get("password"), "board"):
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM new_arrivals WHERE id=?", (arrival_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@new_arrivals_bp.route("/api/new-arrivals/lookup")
def api_new_arrival_lookup():
    isbn = request.args.get("isbn", "").strip().replace("-", "")
    if not isbn:
        return jsonify({"error": "ISBN required"}), 400
    try:
        resp = requests.get(OPENBD_API, params={"isbn": isbn}, timeout=8)
        data = resp.json()
        if data and data[0]:
            s = data[0]["summary"]
            isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
            return jsonify({
                "isbn": isbn,
                "title": s.get("title", ""),
                "author": s.get("author", ""),
                "publisher": s.get("publisher", ""),
                "cover": s.get("cover", "") or get_cover_url(isbn, isbn10)
            })
    except Exception:
        pass
    return jsonify({"isbn": isbn, "title": "", "author": "", "publisher": "", "cover": ""})


@new_arrivals_bp.route("/api/today-book")
def api_today_book():
    import random, datetime
    today = datetime.date.today()
    seed = int(today.strftime("%Y%m%d"))
    rng = random.Random(seed)
    recent = get_recent_isbns()
    if recent:
        rng.shuffle(recent)
        books = recent[:8]
        for b in books:
            isbn = b.get("isbn", "")
            if isbn:
                isbn10 = isbn13_to_isbn10(isbn)
                b["cover"] = get_cover_url(isbn, isbn10)
        return jsonify(books)
    total_pages = 109
    page = rng.randint(1, total_pages)
    try:
        data = fetch_books("", page)
        if data["books"]:
            book = data["books"][rng.randint(0, len(data["books"]) - 1)]
            return jsonify([book])
    except Exception:
        pass
    return jsonify([])


@new_arrivals_bp.route("/api/books/new")
def api_books_new():
    """新着図書一覧：new_arrivalsテーブル優先、なければOpenBD出版日順"""
    try:
        con = get_con()
        rows = fetchall(con, "SELECT isbn,arrived_at,title,author,publisher,cover FROM new_arrivals ORDER BY arrived_at DESC, id DESC LIMIT 100")
        con.close()
        if rows:
            books = []
            for r in rows:
                isbn = r["isbn"]
                isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
                books.append({
                    "isbn": isbn,
                    "isbn10": isbn10,
                    "title": r["title"] or isbn,
                    "author": r["author"] or "",
                    "publisher": r["publisher"] or "",
                    "cover": r["cover"] or get_cover_url(isbn, isbn10),
                    "arrived_at": str(r["arrived_at"])[:10],
                    "format": ""
                })
            return jsonify({"books": books, "source": "registered"})
    except Exception:
        pass
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(fetch_books, "", 1)
            f2 = ex.submit(fetch_books, "", 2)
            data1 = f1.result()
            data2 = f2.result()
        books = data1["books"] + data2["books"]
        isbns = [b["isbn"] for b in books if b.get("isbn") and len(b["isbn"]) == 13]
        ob_resp = requests.get(OPENBD_API, params={"isbn": ",".join(isbns)}, timeout=10)
        ob_data = ob_resp.json()
        pubdate_map = {}
        for item in ob_data:
            if not item:
                continue
            summary = item.get("summary", {})
            isbn = summary.get("isbn", "")
            pubdate = summary.get("pubdate", "")
            if isbn and pubdate:
                pubdate_map[isbn] = pubdate
        for b in books:
            b["pubdate"] = pubdate_map.get(b["isbn"], "")
        books.sort(key=lambda b: b.get("pubdate") or "0", reverse=True)
        return jsonify({"books": books[:100]})
    except Exception as e:
        return jsonify({"books": [], "error": str(e)}), 500


@new_arrivals_bp.route("/api/books/no-review")
def api_books_no_review():
    """書評が未登録（NULLまたは空）の本一覧を返す"""
    from database import fetchone
    con = get_con()
    rows = fetchall(con, """
        SELECT g.isbn, g.title, g.author
        FROM genre_books g
        LEFT JOIN (
            SELECT isbn, MAX(arrived_at) as arrived_at FROM new_arrivals GROUP BY isbn
        ) na ON g.isbn = na.isbn
        WHERE (g.description IS NULL OR g.description = '')
          AND g.manual_review IS NOT TRUE
        ORDER BY na.arrived_at DESC NULLS LAST, g.title
        LIMIT 200
    """)
    con2 = get_con()
    total_row = fetchone(con2, """
        SELECT COUNT(*) as cnt FROM genre_books
        WHERE (description IS NULL OR description = '')
          AND manual_review IS NOT TRUE
    """)
    con.close(); con2.close()
    return jsonify({"books": rows, "total": total_row["cnt"] if total_row else 0})

import json
import concurrent.futures
import requests
from flask import Blueprint, request, jsonify
from config import (
    get_admin_password, get_board_password, OPENBD_API,
    _KANA_ROWS, FULL_STATS,
)
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.utils import rate_limit, _hira_to_kata, _kata_to_hira
from services.books import (
    fetch_books, fetch_book_detail, get_cover_url, get_rating,
    get_ratings_bulk, save_rating, isbn13_to_isbn10,
    get_recent_isbns,
)

books_bp = Blueprint("books", __name__)


@books_bp.route("/api/books")
def api_books():
    keyword = request.args.get("keyword", "")
    page = int(request.args.get("page", 1))
    data = fetch_books(keyword, page)
    isbns = [b["isbn"] for b in data["books"] if b.get("isbn")]
    ratings = get_ratings_bulk(isbns)
    for book in data["books"]:
        book["rating"] = ratings.get(book["isbn"], {"score": 0, "votes": 0, "reviews": []})
    return jsonify(data)


@books_bp.route("/api/book/<isbn>")
def api_book(isbn):
    hint_title = request.args.get("title", "").strip()
    detail = fetch_book_detail(isbn, hint_title=hint_title)
    detail["rating"] = get_rating(isbn)
    con = get_con()
    row = fetchone(con, "SELECT awards FROM genre_books WHERE isbn=%s", (isbn,))
    con.close()
    awards = (row.get("awards") or []) if row else []
    if isinstance(awards, str):
        try: awards = json.loads(awards)
        except: awards = []
    detail["awards"] = awards
    return jsonify(detail)


@books_bp.route("/api/genres")
def api_genres():
    """ジャンル一覧と件数を返す（DBから）"""
    con = get_con()
    rows = fetchall(con, "SELECT genre, COUNT(*) as cnt FROM genre_books GROUP BY genre ORDER BY cnt DESC")
    con.close()
    return jsonify([{"genre": r["genre"], "count": r["cnt"]} for r in rows])


@books_bp.route("/api/books/batch")
def api_books_batch():
    """ISBNリストをDBから一括取得（お気に入り・読書記録用）"""
    isbns_param = request.args.get("isbns", "")
    isbns = [i.strip() for i in isbns_param.split(",") if i.strip()][:50]
    if not isbns:
        return jsonify([])
    con = get_con()
    placeholders = ",".join(["?" for _ in isbns])
    rows = fetchall(con, f"SELECT isbn,title,author,publisher,format FROM genre_books WHERE isbn IN ({placeholders})", tuple(isbns))
    con.close()
    row_map = {r["isbn"]: r for r in rows}
    result = []
    for isbn in isbns:
        r = row_map.get(isbn)
        if r:
            isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
            result.append({**r, "cover": get_cover_url(isbn, isbn10), "rating": {"score":0,"votes":0,"reviews":[]}})
        else:
            result.append({"isbn": isbn, "title": isbn, "author": "", "publisher": "", "cover": "", "rating": {"score":0,"votes":0,"reviews":[]}})
    return jsonify(result)


@books_bp.route("/api/books/by-genre")
def api_books_by_genre():
    """ジャンル別・全件・キーワード・受賞・50音フィルターDB検索（ページネーション付き）"""
    genre    = request.args.get("genre", "")
    keyword  = request.args.get("keyword", "").strip()
    award    = request.args.get("award", "").strip()
    kana_row = request.args.get("kana_row", "").strip()
    page     = int(request.args.get("page", 1))
    per      = min(int(request.args.get("per", 50)), 200)
    offset   = (page - 1) * per
    con = get_con()
    ph = "%s" if USE_PG else "?"
    conditions = []
    params_base = []
    if genre:
        conditions.append(f"genre={ph}")
        params_base.append(genre)
    if kana_row and kana_row in _KANA_ROWS:
        chars = _KANA_ROWS[kana_row]
        kana_conds = " OR ".join([f"title_yomi LIKE {ph}" for _ in chars])
        conditions.append(f"({kana_conds})")
        params_base.extend([c + "%" for c in chars])
    if keyword:
        like = f"%{keyword}%"
        like_kata = f"%{_hira_to_kata(keyword)}%"
        like_hira = f"%{_kata_to_hira(keyword)}%"
        conditions.append(
            f"(title LIKE {ph} OR author LIKE {ph} OR title LIKE {ph} OR title LIKE {ph}"
            f" OR title_yomi LIKE {ph} OR title_yomi LIKE {ph} OR title_yomi LIKE {ph})"
        )
        params_base.extend([like, like, like_kata, like_hira, like, like_hira, like_kata])
    if award:
        if USE_PG:
            if award == "本屋大賞":
                conditions.append("(awards @> %s::jsonb OR awards @> %s::jsonb)")
                params_base.append(json.dumps([{"award": "本屋大賞"}]))
                params_base.append(json.dumps([{"award": "本屋大賞ノミネート"}]))
            else:
                conditions.append("awards @> %s::jsonb")
                params_base.append(json.dumps([{"award": award}]))
        else:
            conditions.append(f"awards LIKE {ph}")
            params_base.append(f"%{award}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params_count = tuple(params_base)
    params_rows  = tuple(params_base) + (per, offset)
    order = "title_yomi ASC, title ASC" if kana_row else "NULLIF(pubdate,'') DESC NULLS LAST, isbn DESC"
    sql_count = f"SELECT COUNT(*) as cnt FROM genre_books {where}"
    sql_rows  = f"SELECT isbn,genre,title,author,publisher,format,awards FROM genre_books {where} ORDER BY {order} LIMIT {ph} OFFSET {ph}"
    total_row = fetchone(con, sql_count, params_count)
    total = total_row["cnt"] if total_row else 0
    rows = fetchall(con, sql_rows, params_rows)
    con.close()
    isbns = [b["isbn"] for b in rows]
    ratings = get_ratings_bulk(isbns)
    result = []
    for b in rows:
        isbn13 = b["isbn"]
        isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
        cover  = get_cover_url(isbn13, isbn10)
        awards_val = b.get("awards") or []
        if isinstance(awards_val, str):
            try: awards_val = json.loads(awards_val)
            except: awards_val = []
        result.append({**b, "isbn10": isbn10, "cover": cover,
                       "awards": awards_val,
                       "rating": ratings.get(isbn13, {"score": 0, "votes": 0, "reviews": []})})
    return jsonify({"books": result, "total": total, "page": page, "genre": genre, "keyword": keyword, "award": award})


@books_bp.route("/api/stats")
def api_stats():
    return jsonify(FULL_STATS)


@books_bp.route("/api/new-arrivals")
def api_get_new_arrivals():
    con = get_con()
    rows = fetchall(con, "SELECT id,isbn,arrived_at,title,author,publisher,cover FROM new_arrivals ORDER BY arrived_at DESC, id DESC")
    con.close()
    return jsonify([{**r, "arrived_at": str(r["arrived_at"])[:10]} for r in rows])


@books_bp.route("/api/new-arrivals", methods=["POST"])
def api_post_new_arrival():
    body = request.get_json()
    if body.get("password") != get_board_password():
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


@books_bp.route("/api/new-arrivals/<int:arrival_id>", methods=["DELETE"])
def api_delete_new_arrival(arrival_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM new_arrivals WHERE id=?", (arrival_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@books_bp.route("/api/new-arrivals/lookup")
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


@books_bp.route("/api/today-book")
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


@books_bp.route("/api/books/new")
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


@books_bp.route("/api/books/no-review")
def api_books_no_review():
    """書評が未登録（NULLまたは空）の本一覧を返す"""
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


@books_bp.route("/api/books/related/<isbn>")
def api_books_related(isbn):
    """同じ著者・同じジャンルの本を返す（モーダル用）"""
    con = get_con()
    book = fetchone(con, "SELECT author, genre FROM genre_books WHERE isbn=?", (isbn,))
    if not book:
        con.close()
        return jsonify({"same_author": [], "same_genre": []})
    author = book["author"]
    genre = book["genre"]
    same_author = fetchall(con,
        "SELECT isbn, title, author FROM genre_books WHERE author=? AND isbn!=? ORDER BY isbn DESC LIMIT 20",
        (author, isbn))
    same_genre = fetchall(con,
        "SELECT isbn, title, author FROM genre_books WHERE genre=? AND isbn!=? AND (author!=? OR author IS NULL) ORDER BY isbn DESC LIMIT 20",
        (genre, isbn, author))
    con.close()
    def enrich(rows):
        result = []
        for b in rows:
            isbn13 = b["isbn"]
            isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
            result.append({"isbn": isbn13, "title": b["title"], "author": b["author"], "cover": get_cover_url(isbn13, isbn10)})
        return result
    return jsonify({"same_author": enrich(same_author), "same_genre": enrich(same_genre)})


@books_bp.route("/api/helpful", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_helpful():
    body = request.get_json()
    isbn = body.get("isbn", "").strip()
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "UPDATE genre_books SET helpful_count = COALESCE(helpful_count,0) + 1 WHERE isbn=%s" if USE_PG else "UPDATE genre_books SET helpful_count = COALESCE(helpful_count,0) + 1 WHERE isbn=?", (isbn,))
    con.commit()
    row = fetchone(con, "SELECT helpful_count FROM genre_books WHERE isbn=%s" if USE_PG else "SELECT helpful_count FROM genre_books WHERE isbn=?", (isbn,))
    con.close()
    return jsonify({"helpful_count": row["helpful_count"] if row else 1})


@books_bp.route("/api/rate", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_rate():
    body = request.get_json()
    isbn = body.get("isbn", "")
    score = int(body.get("score", 0))
    review = body.get("review", "")
    if not isbn or score < 1 or score > 5:
        return jsonify({"error": "invalid"}), 400
    save_rating(isbn, score, review)
    return jsonify(get_rating(isbn))


@books_bp.route("/api/book-description", methods=["POST"])
def api_book_description():
    body = request.get_json()
    password = body.get("password", "")
    if password != get_admin_password() and password != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    isbn = body.get("isbn", "").strip()
    description = body.get("description", "").strip()[:600]
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "UPDATE genre_books SET description=?, manual_review=TRUE, manual_review_date=CURRENT_DATE WHERE isbn=?", (description, isbn))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@books_bp.route("/api/book-award", methods=["POST"])
def api_book_award():
    """受賞情報の設定（管理者のみ）"""
    body = request.get_json()
    password = body.get("password", "")
    if password != get_admin_password() and password != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    isbn = body.get("isbn", "").strip()
    awards = body.get("awards", [])
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "UPDATE genre_books SET awards=%s WHERE isbn=%s", (json.dumps(awards, ensure_ascii=False), isbn))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@books_bp.route("/api/book-awards/<isbn>")
def api_book_awards_get(isbn):
    """本の受賞情報取得"""
    con = get_con()
    row = fetchone(con, "SELECT awards FROM genre_books WHERE isbn=%s", (isbn,))
    con.close()
    if not row:
        return jsonify({"awards": []})
    awards = row.get("awards") or []
    if isinstance(awards, str):
        try: awards = json.loads(awards)
        except: awards = []
    return jsonify({"awards": awards})


@books_bp.route("/api/awards/list")
def api_awards_list():
    """受賞情報がある本の一覧（フィルター用）"""
    con = get_con()
    if USE_PG:
        rows = fetchall(con, "SELECT isbn, title, author, awards FROM genre_books WHERE awards IS NOT NULL AND awards != '[]'::jsonb ORDER BY isbn DESC")
    else:
        rows = fetchall(con, "SELECT isbn, title, author, awards FROM genre_books WHERE awards IS NOT NULL AND awards != '[]' ORDER BY isbn DESC")
    con.close()
    result = []
    for r in rows:
        awards = r.get("awards") or []
        if isinstance(awards, str):
            try: awards = json.loads(awards)
            except: awards = []
        if awards:
            result.append({"isbn": r["isbn"], "title": r["title"], "author": r["author"], "awards": awards})
    return jsonify({"books": result})


@books_bp.route("/api/collections")
def api_collections_get():
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


@books_bp.route("/api/collections", methods=["POST"])
def api_collections_post():
    body = request.get_json()
    if body.get("password") != get_board_password():
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


@books_bp.route("/api/collections/<int:cid>", methods=["PATCH"])
def api_collections_patch(cid):
    body = request.get_json()
    if body.get("password") != get_board_password():
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


@books_bp.route("/api/collections/<int:cid>", methods=["DELETE"])
def api_collections_delete(cid):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM collections WHERE id=?", (cid,))
    con.commit(); con.close()
    return jsonify({"ok": True})

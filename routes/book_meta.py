import json
from flask import Blueprint, request, jsonify
from config import check_password
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.books import get_ratings_bulk

book_meta_bp = Blueprint("book_meta", __name__)


@book_meta_bp.route("/api/book-description", methods=["POST"])
def api_book_description():
    body = request.get_json()
    password = body.get("password", "")
    if not (check_password(password, "admin") or check_password(password, "board")):
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


@book_meta_bp.route("/api/book-award", methods=["POST"])
def api_book_award():
    """受賞情報の設定（管理者のみ）"""
    body = request.get_json()
    password = body.get("password", "")
    if not (check_password(password, "admin") or check_password(password, "board")):
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


@book_meta_bp.route("/api/book-awards/<isbn>")
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


@book_meta_bp.route("/api/awards/list")
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


@book_meta_bp.route("/api/tags/popular")
def api_tags_popular():
    """ai_tags から人気タグTOP30を返す"""
    con = get_con()
    rows = fetchall(con, "SELECT ai_tags FROM genre_books WHERE ai_tags IS NOT NULL AND ai_tags != '[]' AND ai_tags != ''")
    con.close()
    from collections import Counter
    counter = Counter()
    for row in rows:
        try:
            tags = json.loads(row["ai_tags"]) if isinstance(row["ai_tags"], str) else row["ai_tags"]
            if isinstance(tags, list):
                counter.update(tags)
        except Exception:
            pass
    top = [{"tag": t, "count": c} for t, c in counter.most_common(30)]
    return jsonify({"tags": top})


@book_meta_bp.route("/api/books/by-tag")
def api_books_by_tag():
    """指定タグを含む書籍をDBから返す"""
    tag = request.args.get("tag", "").strip()
    page = int(request.args.get("page", 1))
    limit = 20
    offset = (page - 1) * limit
    if not tag:
        return jsonify({"books": [], "total": 0, "page": page})
    con = get_con()
    if USE_PG:
        rows = fetchall(con,
            "SELECT isbn, title, author, ai_tags FROM genre_books WHERE ai_tags::jsonb @> %s::jsonb ORDER BY title LIMIT %s OFFSET %s",
            (json.dumps([tag]), limit, offset))
        total_row = fetchone(con,
            "SELECT COUNT(*) as cnt FROM genre_books WHERE ai_tags::jsonb @> %s::jsonb",
            (json.dumps([tag]),))
    else:
        rows = fetchall(con,
            "SELECT isbn, title, author, ai_tags FROM genre_books WHERE ai_tags LIKE ? ORDER BY title LIMIT ? OFFSET ?",
            (f'%"{tag}"%', limit, offset))
        total_row = fetchone(con,
            "SELECT COUNT(*) as cnt FROM genre_books WHERE ai_tags LIKE ?",
            (f'%"{tag}"%',))
    con.close()
    isbns = [r["isbn"] for r in rows if r.get("isbn")]
    ratings = get_ratings_bulk(isbns)
    books = []
    for r in rows:
        books.append({
            "isbn": r["isbn"],
            "title": r["title"],
            "author": r["author"],
            "rating": ratings.get(r["isbn"], {"score": 0, "votes": 0, "reviews": []}),
        })
    return jsonify({"books": books, "total": total_row["cnt"] if total_row else 0, "page": page, "tag": tag})

import json
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

from config import (
    get_admin_password, get_board_password, OPENBD_API,
    _KANA_ROWS, check_password,
)
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.utils import rate_limit, _hira_to_kata, _kata_to_hira
from services.books import (
    fetch_books, fetch_book_detail, get_cover_url, get_rating,
    get_ratings_bulk, save_rating, delete_review, isbn13_to_isbn10,
    get_recent_isbns,
)

books_bp = Blueprint("books", __name__)


@books_bp.route("/api/books/suggest")
def api_books_suggest():
    """タイトル・著者のオートコンプリート候補（最大10件）"""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    from database import get_con, USE_PG
    from services.utils import _hira_to_kata, _kata_to_hira
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        like = f"%{q}%"
        like_kata = f"%{_hira_to_kata(q)}%"
        like_hira = f"%{_kata_to_hira(q)}%"
        rows = fetchall(con, f"""
            SELECT isbn, title, author FROM genre_books
            WHERE title LIKE {ph} OR title LIKE {ph} OR title LIKE {ph}
               OR author LIKE {ph} OR author LIKE {ph} OR author LIKE {ph}
            LIMIT 10
        """, (like, like_kata, like_hira, like, like_kata, like_hira))
        con.close()
        seen = set()
        result = []
        for r in rows:
            key = (r["title"], r["author"])
            if key not in seen:
                seen.add(key)
                result.append({"isbn": r["isbn"], "title": r["title"] or "", "author": r["author"] or ""})
        return jsonify(result)
    except Exception as e:
        con.close()
        return jsonify([])


@books_bp.route("/api/books")
def api_books():
    keyword = request.args.get("keyword", "")
    page = int(request.args.get("page", 1))
    data = fetch_books(keyword, page)
    isbns = [b["isbn"] for b in data["books"] if b.get("isbn")]
    ratings = get_ratings_bulk(isbns)
    helpful_counts = {}
    if isbns:
        try:
            con = get_con()
            ph = "%s" if USE_PG else "?"
            placeholders = ",".join([ph] * len(isbns))
            rows = fetchall(con, f"SELECT isbn, helpful_count FROM genre_books WHERE isbn IN ({placeholders})", tuple(isbns))
            con.close()
            helpful_counts = {r["isbn"]: (r.get("helpful_count") or 0) for r in rows}
        except Exception:
            pass
    for book in data["books"]:
        book["rating"] = ratings.get(book["isbn"], {"score": 0, "votes": 0, "reviews": []})
        book["helpful_count"] = helpful_counts.get(book["isbn"], 0)
    return jsonify(data)


@books_bp.route("/api/book/<isbn>")
def api_book(isbn):
    hint_title = request.args.get("title", "").strip()
    detail = fetch_book_detail(isbn, hint_title=hint_title)
    viewer_room = request.args.get("room", "").strip() or None
    try:
        detail["rating"] = get_rating(isbn, viewer_room=viewer_room)
    except Exception:
        detail["rating"] = {"score": 0, "votes": 0, "reviews": [], "my_score": None}
    try:
        con = get_con()
        row = fetchone(con, "SELECT awards FROM genre_books WHERE isbn=?", (isbn,))
        con.close()
        awards = (row.get("awards") or []) if row else []
        if isinstance(awards, str):
            try: awards = json.loads(awards)
            except: awards = []
    except Exception:
        awards = []
    detail["awards"] = awards
    return jsonify(detail)


@books_bp.route("/api/genres")
def api_genres():
    """ジャンル一覧と件数を返す（DBから）"""
    con = get_con()
    rows = fetchall(con, "SELECT genre, COUNT(*) as cnt FROM genre_books GROUP BY genre ORDER BY cnt DESC")
    con.close()
    return jsonify([{"genre": r["genre"], "count": r["cnt"]} for r in rows])


def _genre_award_books(genre: str, ph: str, con) -> list[dict]:
    """指定ジャンルの本のうち受賞歴があるものを、受賞数→最新受賞年の順で返す。
    v1.3 Phase2: 「代表作品」「受賞作品」セクション向け。"""
    rows = fetchall(con, f"SELECT isbn, title, author, awards FROM genre_books WHERE genre={ph}", (genre,))
    scored = []
    for r in rows:
        raw = r.get("awards")
        try:
            awards = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            awards = []
        if not awards:
            continue
        years = [int(a.get("year") or 0) for a in awards]
        label_parts = [f"{a.get('award','')}{a.get('year','')}" for a in awards[:2]]
        scored.append({
            "isbn": r["isbn"], "title": r["title"], "author": r.get("author", ""),
            "award_count": len(awards), "latest_year": max(years) if years else 0,
            "award_label": "・".join(label_parts),
        })
    scored.sort(key=lambda x: (-x["award_count"], -x["latest_year"]))
    return scored


def _genre_popular_books(genre: str, ph: str, con) -> list[dict]:
    """指定ジャンルの本を、星評価×お気に入り数の合算スコアで人気順に返す。
    /api/books/popular と同じスコアリングをジャンル限定で適用する。"""
    rating_rows = fetchall(con, "SELECT isbn, score, votes FROM ratings WHERE votes >= 1 AND score >= 1")
    rating_map = {r["isbn"]: {"score": r["score"], "votes": r["votes"]} for r in rating_rows}
    fav_rows = fetchall(con, "SELECT favorites FROM user_accounts WHERE favorites IS NOT NULL AND favorites != '[]'")
    fav_count: dict[str, int] = {}
    for row in fav_rows:
        try:
            for isbn in json.loads(row["favorites"] or "[]"):
                if isbn:
                    fav_count[isbn] = fav_count.get(isbn, 0) + 1
        except Exception:
            pass

    all_isbns = set(rating_map) | set(fav_count)
    if not all_isbns:
        return []
    placeholders = ",".join([ph] * len(all_isbns))
    genre_rows = fetchall(
        con, f"SELECT isbn, title, author FROM genre_books WHERE genre={ph} AND isbn IN ({placeholders})",
        (genre, *all_isbns))
    genre_isbns = {r["isbn"]: r for r in genre_rows}

    scored = []
    for isbn, book in genre_isbns.items():
        r = rating_map.get(isbn, {})
        fav = fav_count.get(isbn, 0)
        composite = r.get("score", 0) * r.get("votes", 0) * 2 + fav * 0.5
        if composite <= 0:
            continue
        scored.append({
            "isbn": isbn, "title": book["title"], "author": book.get("author", ""),
            "score": r.get("score", 0.0), "votes": r.get("votes", 0), "fav_count": fav,
            "composite": composite,
        })
    scored.sort(key=lambda x: -x["composite"])
    return scored


@books_bp.route("/api/genres/info")
def api_genre_info():
    """ジャンル紹介文（特徴・おすすめの読者・初めて読むなら）と、
    代表作品・受賞作品・人気作品をまとめて返す。
    v1.3: ジャンルページを「一覧」から「読書ガイド」へ育てる。
    1回のリクエストでジャンルページに必要な情報をすべて取得できるようにし、
    フロント実装をシンプルに保つ（Phase1のBridge Worksコーナーは既存の
    /api/plam/bridge-recommend?cluster=X を継続利用し、ここには含めない）。"""
    from config import GENRE_DESCRIPTIONS
    genre = request.args.get("genre", "").strip()
    info = GENRE_DESCRIPTIONS.get(genre)
    if not info:
        return jsonify({"genre": genre, "found": False})

    con = get_con()
    ph = "%s" if USE_PG else "?"
    award_books = _genre_award_books(genre, ph, con)
    popular_books = _genre_popular_books(genre, ph, con)
    con.close()

    return jsonify({
        "genre": genre, "found": True, **info,
        "first_books": award_books[:3],
        "award_books": award_books[3:8],
        "popular_books": popular_books[:5],
    })


@books_bp.route("/api/books/batch")
def api_books_batch():
    """ISBNリストをDBから一括取得（お気に入り・読書記録用）"""
    isbns_param = request.args.get("isbns", "")
    isbns = [i.strip() for i in isbns_param.split(",") if i.strip()][:50]
    if not isbns:
        return jsonify([])
    con = get_con()
    ph = "%s" if USE_PG else "?"
    placeholders = ",".join([ph for _ in isbns])
    rows = fetchall(con, f"SELECT isbn,title,author,publisher,format,genre FROM genre_books WHERE isbn IN ({placeholders})", tuple(isbns))
    con.close()
    row_map = {r["isbn"]: r for r in rows}
    result = []
    for isbn in isbns:
        r = row_map.get(isbn)
        if r:
            isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
            result.append({**r, "isbn10": isbn10, "cover": get_cover_url(isbn, isbn10), "rating": {"score":0,"votes":0,"reviews":[]}})
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
    if kana_row:
        selected_rows = [r for r in kana_row.split(",") if r in _KANA_ROWS]
        if selected_rows:
            all_chars = [c for r in selected_rows for c in _KANA_ROWS[r]]
            kana_conds = " OR ".join([f"title_yomi LIKE {ph}" for _ in all_chars])
            conditions.append(f"({kana_conds})")
            params_base.extend([c + "%" for c in all_chars])
    if keyword:
        like = f"%{keyword}%"
        like_kata = f"%{_hira_to_kata(keyword)}%"
        like_hira = f"%{_kata_to_hira(keyword)}%"
        conditions.append(
            f"(title LIKE {ph} OR author LIKE {ph} OR title LIKE {ph} OR title LIKE {ph}"
            f" OR title_yomi LIKE {ph} OR title_yomi LIKE {ph} OR title_yomi LIKE {ph}"
            f" OR ai_summary LIKE {ph} OR ai_tags LIKE {ph})"
        )
        params_base.extend([like, like, like_kata, like_hira, like, like_hira, like_kata, like, like])
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
    _ALLOWED_ORDERS = {
        "kana": "title_yomi ASC, title ASC",
        "new":  "NULLIF(pubdate,'') DESC NULLS LAST, isbn DESC",
    }
    order = _ALLOWED_ORDERS["kana"] if kana_row else _ALLOWED_ORDERS["new"]
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
    """蔵書統計を実データから動的集計する（旧FULL_STATSは librarylife同期で増減する
    蔵書件数に対して固定値のまま乖離していたため廃止）。"""
    con = get_con()
    total_row = fetchone(con, "SELECT COUNT(*) AS cnt FROM genre_books")
    total = total_row["cnt"] if total_row else 0

    genre_rows = fetchall(con, "SELECT genre, COUNT(*) AS cnt FROM genre_books GROUP BY genre ORDER BY cnt DESC")
    publisher_rows = fetchall(con, """
        SELECT publisher, COUNT(*) AS cnt FROM genre_books
        WHERE publisher IS NOT NULL AND publisher != ''
        GROUP BY publisher ORDER BY cnt DESC LIMIT 50
    """)
    author_rows = fetchall(con, """
        SELECT author, COUNT(*) AS cnt FROM genre_books
        WHERE author IS NOT NULL AND author != ''
        GROUP BY author ORDER BY cnt DESC LIMIT 50
    """)
    format_rows = fetchall(con, "SELECT format, COUNT(*) AS cnt FROM genre_books GROUP BY format ORDER BY cnt DESC")

    if USE_PG:
        rating_rows = fetchall(con, """
            SELECT ROUND(score::numeric) AS star, COUNT(*) AS cnt
            FROM ratings WHERE votes > 0 GROUP BY ROUND(score::numeric) ORDER BY star DESC
        """)
    else:
        rating_rows = fetchall(con, """
            SELECT ROUND(score) AS star, COUNT(*) AS cnt
            FROM ratings WHERE votes > 0 GROUP BY ROUND(score) ORDER BY star DESC
        """)
    con.close()

    return jsonify({
        "total": total,
        "genres": [[r["genre"] or "未分類", r["cnt"]] for r in genre_rows],
        "publishers": [[r["publisher"], r["cnt"]] for r in publisher_rows],
        "authors": [[r["author"], r["cnt"]] for r in author_rows],
        "formats": [[r["format"] or "不明", r["cnt"]] for r in format_rows],
        "rating_distribution": [[int(r["star"]), r["cnt"]] for r in rating_rows if r["star"] is not None],
    })


@books_bp.route("/api/books/popular")
def api_books_popular():
    """住民人気ランキング（星評価×2 ＋ お気に入り数×0.5 の合算スコア上位20件）"""
    con = get_con()

    # ── 星評価データ ──
    rating_rows = fetchall(con, "SELECT isbn, score, votes FROM ratings WHERE votes >= 1 AND score >= 1")
    rating_map = {r["isbn"]: {"score": r["score"], "votes": r["votes"]} for r in rating_rows}

    # ── お気に入りデータ（全ユーザー集計） ──
    fav_rows = fetchall(con, "SELECT favorites FROM user_accounts WHERE favorites IS NOT NULL AND favorites != '[]'")
    fav_count: dict[str, int] = {}
    for row in fav_rows:
        try:
            for isbn in json.loads(row["favorites"] or "[]"):
                if isbn:
                    fav_count[isbn] = fav_count.get(isbn, 0) + 1
        except Exception:
            pass

    con.close()

    # ── 合算スコアを計算（星評価がある本を優先、ない本はお気に入り数で補完） ──
    all_isbns = set(rating_map) | set(fav_count)
    candidates = []
    for isbn in all_isbns:
        r   = rating_map.get(isbn, {})
        fav = fav_count.get(isbn, 0)
        if not r and fav == 0:
            continue
        composite = r.get("score", 0) * r.get("votes", 0) * 2 + fav * 0.5
        candidates.append({
            "isbn": isbn,
            "composite": composite,
            "score": r.get("score", 0.0),
            "votes": r.get("votes", 0),
            "fav_count": fav,
        })

    candidates.sort(key=lambda x: x["composite"], reverse=True)
    top20 = candidates[:20]
    if not top20:
        return jsonify([])

    # ── 書籍情報を一括取得 ──
    con2 = get_con()
    ph = "%s" if USE_PG else "?"
    placeholders = ",".join([ph] * len(top20))
    book_rows = fetchall(con2, f"SELECT isbn,title,author FROM genre_books WHERE isbn IN ({placeholders})", tuple(c["isbn"] for c in top20))
    con2.close()
    book_map = {b["isbn"]: b for b in book_rows}

    result = []
    for c in top20:
        b = book_map.get(c["isbn"])
        if not b:
            continue
        isbn13 = c["isbn"]
        isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
        result.append({
            "isbn": isbn13, "isbn10": isbn10,
            "title": b["title"], "author": b["author"],
            "cover": get_cover_url(isbn13, isbn10),
            "score": round(c["score"], 1),
            "votes": c["votes"],
            "fav_count": c["fav_count"],
        })
    return jsonify(result)


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
            result.append({"isbn": isbn13, "isbn10": isbn10, "title": b["title"], "author": b["author"], "cover": get_cover_url(isbn13, isbn10)})
        return result
    return jsonify({"same_author": enrich(same_author), "same_genre": enrich(same_genre)})

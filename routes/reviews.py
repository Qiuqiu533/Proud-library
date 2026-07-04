from flask import Blueprint, request, jsonify
from database import get_con, execute, fetchone, USE_PG
from services.utils import rate_limit
from services.books import get_rating, save_rating, delete_review

reviews_bp = Blueprint("reviews", __name__)


@reviews_bp.route("/api/helpful", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_helpful():
    import hashlib
    body = request.get_json()
    isbn = body.get("isbn", "").strip()
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    # 投票者の識別: IPアドレス + User-Agent をハッシュ化（個人情報を保存しない）
    voter_raw = (request.remote_addr or "") + (request.headers.get("User-Agent", ""))
    voter_hash = hashlib.sha256(voter_raw.encode()).hexdigest()
    con = get_con()
    ph = "%s" if USE_PG else "?"
    existing = fetchone(con, f"SELECT 1 FROM helpful_votes WHERE isbn={ph} AND voter_hash={ph}", (isbn, voter_hash))
    if existing:
        row = fetchone(con, f"SELECT helpful_count FROM genre_books WHERE isbn={ph}", (isbn,))
        con.close()
        return jsonify({"helpful_count": row["helpful_count"] if row else 0, "already_voted": True})
    if USE_PG:
        execute(con, "INSERT INTO helpful_votes (isbn, voter_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING", (isbn, voter_hash))
    else:
        execute(con, "INSERT OR IGNORE INTO helpful_votes (isbn, voter_hash) VALUES (?, ?)", (isbn, voter_hash))
    execute(con, f"UPDATE genre_books SET helpful_count = COALESCE(helpful_count,0) + 1 WHERE isbn={ph}", (isbn,))
    con.commit()
    row = fetchone(con, f"SELECT helpful_count FROM genre_books WHERE isbn={ph}", (isbn,))
    con.close()
    return jsonify({"helpful_count": row["helpful_count"] if row else 1})


@reviews_bp.route("/api/rate", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_rate():
    from database import fetchone as _fetchone
    body = request.get_json()
    isbn   = body.get("isbn", "")
    score  = int(body.get("score", 0))
    review = body.get("review", "")
    room   = (body.get("room") or "").strip() or None
    password = (body.get("password") or "").strip()
    if not isbn or score < 1 or score > 5:
        return jsonify({"error": "invalid"}), 400
    # ログイン済みユーザーは認証確認
    if room:
        con = get_con()
        user = _fetchone(con, "SELECT password_hash, password_salt FROM user_accounts WHERE room=?", (room,))
        con.close()
        if not user:
            room = None  # 未登録部屋は匿名扱い
        else:
            from services.utils import _verify_password
            if not _verify_password(password, user["password_hash"], user.get("password_salt") or ""):
                return jsonify({"error": "認証に失敗しました"}), 401
    save_rating(isbn, score, review, room=room)
    return jsonify(get_rating(isbn, viewer_room=room))


@reviews_bp.route("/api/rate/review", methods=["DELETE"])
@rate_limit(limit=20, window=60)
def api_delete_review():
    from database import fetchone as _fetchone
    body = request.get_json()
    isbn      = (body.get("isbn") or "").strip()
    review_id = (body.get("review_id") or "").strip()
    room      = (body.get("room") or "").strip()
    password  = (body.get("password") or "").strip()
    if not isbn or not review_id or not room:
        return jsonify({"error": "invalid"}), 400
    con = get_con()
    user = _fetchone(con, "SELECT password_hash, password_salt FROM user_accounts WHERE room=?", (room,))
    con.close()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    from services.utils import _verify_password
    if not _verify_password(password, user["password_hash"], user.get("password_salt") or ""):
        return jsonify({"error": "認証に失敗しました"}), 401
    if not delete_review(isbn, review_id, room):
        return jsonify({"error": "削除できません"}), 404
    return jsonify(get_rating(isbn, viewer_room=room))

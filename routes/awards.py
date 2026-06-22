from flask import Blueprint, request, jsonify
from config import get_board_password
from database import get_con, execute, fetchone, fetchall, USE_PG
from services.audit import log_action

awards_bp = Blueprint("awards", __name__)


@awards_bp.route("/api/award-books")
def api_award_books():
    """受賞作一覧取得。?award=三島由紀夫賞 でフィルター"""
    award = request.args.get("award", "").strip()
    if not USE_PG:
        return jsonify([])
    con = get_con()
    if award:
        rows = fetchall(con, "SELECT * FROM award_books WHERE award=? AND status='確認済' ORDER BY award_year DESC, award_no DESC", (award,))
    else:
        rows = fetchall(con, "SELECT * FROM award_books WHERE status='確認済' ORDER BY award, award_year DESC, award_no DESC")
    con.close()
    try:
        con2 = get_con()
        lib_rows = fetchall(con2, "SELECT isbn, title, author FROM genre_books")
        con2.close()
        lib_map = {}
        for r in lib_rows:
            key = (r["title"].strip(), r["author"].strip())
            lib_map[key] = r["isbn"]
    except Exception:
        lib_map = {}
    result = []
    for r in rows:
        d = dict(r)
        key = (d.get("title", "").strip(), d.get("author", "").strip())
        d["in_library"] = key in lib_map
        d["library_isbn"] = lib_map.get(key, "")
        result.append(d)
    return jsonify(result)


@awards_bp.route("/api/award-books/awards")
def api_award_books_awards():
    """登録済み賞名一覧を返す"""
    if not USE_PG:
        return jsonify([])
    con = get_con()
    rows = fetchall(con, "SELECT DISTINCT award, COUNT(*) as cnt FROM award_books WHERE status='確認済' GROUP BY award ORDER BY award")
    con.close()
    return jsonify([{"award": r["award"], "count": r["cnt"]} for r in rows])


@awards_bp.route("/api/award-books", methods=["POST"])
def api_post_award_book():
    """受賞作を1件追加（管理者）"""
    data = request.get_json() or {}
    password = data.get("password", "")
    if password != get_board_password():
        return jsonify({"error": "認証エラー"}), 403
    award   = (data.get("award") or "").strip()
    title   = (data.get("title") or "").strip()
    author  = (data.get("author") or "").strip()
    year    = data.get("award_year")
    no      = data.get("award_no")
    status  = (data.get("status") or "確認済").strip()
    if not award or not title:
        return jsonify({"error": "賞名とタイトルは必須です"}), 400
    if not USE_PG:
        return jsonify({"error": "PG only"}), 400
    con = get_con()
    execute(con, "INSERT INTO award_books (award, award_no, award_year, title, author, status) VALUES (?,?,?,?,?,?)",
            (award, no, year, title, author, status))
    con.commit()
    con.close()
    log_action("受賞作登録", f"{award}／{title}", f"著者={author} 年={year}")
    return jsonify({"ok": True})


@awards_bp.route("/api/award-books/<int:book_id>", methods=["PATCH"])
def api_patch_award_book(book_id):
    """受賞作のステータスを更新（管理者）"""
    data = request.get_json() or {}
    if data.get("password", "") != get_board_password():
        return jsonify({"error": "認証エラー"}), 403
    status = (data.get("status") or "").strip()
    if status not in ("確認済", "要確認"):
        return jsonify({"error": "不正なステータス"}), 400
    if not USE_PG:
        return jsonify({"error": "PG only"}), 400
    con = get_con()
    execute(con, "UPDATE award_books SET status=? WHERE id=?", (status, book_id))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@awards_bp.route("/api/award-books/<int:book_id>", methods=["DELETE"])
def api_delete_award_book(book_id):
    """受賞作を削除（管理者）"""
    data = request.get_json() or {}
    if data.get("password", "") != get_board_password():
        return jsonify({"error": "認証エラー"}), 403
    if not USE_PG:
        return jsonify({"error": "PG only"}), 400
    con = get_con()
    execute(con, "DELETE FROM award_books WHERE id=?", (book_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@awards_bp.route("/api/award-books/admin")
def api_award_books_admin():
    """管理者用：全ステータス・全賞の一覧（フィルター対応）"""
    if not USE_PG:
        return jsonify([])
    award = request.args.get("award", "").strip()
    password = request.headers.get("X-Password", "")
    if password != get_board_password():
        return jsonify({"error": "認証エラー"}), 403
    con = get_con()
    if award:
        rows = fetchall(con, "SELECT * FROM award_books WHERE award=? ORDER BY award_year DESC, award_no DESC, id DESC", (award,))
    else:
        rows = fetchall(con, "SELECT * FROM award_books ORDER BY award, award_year DESC, award_no DESC")
    con.close()
    return jsonify([dict(r) for r in rows])

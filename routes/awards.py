from flask import Blueprint, request, jsonify
from config import get_board_password, check_password
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
    def _norm(s):
        """タイトル・著者の正規化（スペース除去・全角半角統一）"""
        import unicodedata
        s = unicodedata.normalize("NFKC", s or "").strip()
        return "".join(s.split())

    try:
        con2 = get_con()
        lib_rows = fetchall(con2, "SELECT isbn, title, author FROM genre_books")
        con2.close()
        lib_map = {}       # (正規化タイトル, 正規化著者) → isbn
        lib_title_map = {} # 正規化タイトルのみ → isbn（著者が異なる場合のフォールバック）
        for r in lib_rows:
            nt = _norm(r["title"])
            na = _norm(r["author"])
            lib_map[(nt, na)] = r["isbn"]
            if nt not in lib_title_map:
                lib_title_map[nt] = r["isbn"]
    except Exception:
        lib_map = {}
        lib_title_map = {}
    result = []
    for r in rows:
        d = dict(r)
        nt = _norm(d.get("title", ""))
        na = _norm(d.get("author", ""))
        isbn = lib_map.get((nt, na)) or lib_title_map.get(nt, "")
        d["in_library"] = bool(isbn)
        d["library_isbn"] = isbn
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
    if not check_password(password, "board"):
        return jsonify({"error": "認証エラー"}), 403
    award   = (data.get("award") or "").strip()
    title   = (data.get("title") or "").strip()
    author  = (data.get("author") or "").strip()
    year    = data.get("award_year")
    no      = data.get("award_no")
    isbn13  = (data.get("isbn13") or "").strip()
    status  = (data.get("status") or "確認済").strip()
    if not award or not title:
        return jsonify({"error": "賞名とタイトルは必須です"}), 400
    if not USE_PG:
        return jsonify({"error": "PG only"}), 400
    con = get_con()
    execute(con, "INSERT INTO award_books (award, award_no, award_year, title, author, isbn13, status) VALUES (?,?,?,?,?,?,?)",
            (award, no, year, title, author, isbn13, status))
    con.commit()
    con.close()
    log_action("受賞作登録", f"{award}／{title}", f"著者={author} 年={year}")
    return jsonify({"ok": True})


@awards_bp.route("/api/award-books/<int:book_id>", methods=["PATCH"])
def api_patch_award_book(book_id):
    """受賞作のステータス・ISBN更新（管理者）"""
    data = request.get_json() or {}
    if not check_password(data.get("password", ""), "board"):
        return jsonify({"error": "認証エラー"}), 403
    if not USE_PG:
        return jsonify({"error": "PG only"}), 400
    con = get_con()
    if "isbn13" in data:
        import re
        isbn = re.sub(r"[^0-9X]", "", (data.get("isbn13") or "").upper().strip())
        if isbn and len(isbn) not in (10, 13):
            con.close()
            return jsonify({"error": "ISBNは10桁または13桁で入力してください"}), 400
        execute(con, "UPDATE award_books SET isbn13=? WHERE id=?", (isbn or None, book_id))
    elif "status" in data:
        status = (data.get("status") or "").strip()
        if status not in ("確認済", "要確認"):
            con.close()
            return jsonify({"error": "不正なステータス"}), 400
        execute(con, "UPDATE award_books SET status=? WHERE id=?", (status, book_id))
    else:
        con.close()
        return jsonify({"error": "更新フィールドなし"}), 400
    con.commit()
    con.close()
    return jsonify({"ok": True})


@awards_bp.route("/api/award-books/<int:book_id>", methods=["DELETE"])
def api_delete_award_book(book_id):
    """受賞作を削除（管理者）"""
    data = request.get_json() or {}
    if not check_password(data.get("password", ""), "board"):
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
    if not check_password(password, "board"):
        return jsonify({"error": "認証エラー"}), 403
    con = get_con()
    if award:
        rows = fetchall(con, "SELECT * FROM award_books WHERE award=? ORDER BY award_year DESC, award_no DESC, id DESC", (award,))
    else:
        rows = fetchall(con, "SELECT * FROM award_books ORDER BY award, award_year DESC, award_no DESC")
    con.close()
    return jsonify([dict(r) for r in rows])

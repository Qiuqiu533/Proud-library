from flask import Blueprint, jsonify, render_template, request
from services.plam import get_award_network, get_bridge_works, get_book_plam_info, get_related_works, get_my_plam
from database import get_con
from config import check_password

plam_bp = Blueprint("plam", __name__)


@plam_bp.route("/plam")
def plam_page():
    return render_template("plam_network.html")


@plam_bp.route("/api/plam/network")
def api_plam_network():
    """Cytoscape.js 向け賞ネットワークデータ"""
    return jsonify(get_award_network())


@plam_bp.route("/api/plam/bridge-works")
def api_plam_bridge_works():
    """クラスタ横断作品（Bridge Works）一覧"""
    limit = 50
    return jsonify(get_bridge_works(limit=limit))


@plam_bp.route("/api/plam/related")
def api_plam_related():
    """PLAMネットワーク経由の関連作品推薦"""
    work_id = request.args.get("work_id", "").strip()
    if not work_id:
        return jsonify({"error": "work_id required"}), 400
    limit = min(int(request.args.get("limit", 6)), 12)
    return jsonify(get_related_works(work_id, limit=limit))


@plam_bp.route("/api/plam/my")
def api_plam_my():
    """住民の読了履歴からMy PLAMプロフィールを返す"""
    room = request.args.get("room", "").strip()
    if not room:
        return jsonify({"error": "room required"}), 400
    result = get_my_plam(room)
    if result is None:
        return jsonify(None), 200
    return jsonify(result)


@plam_bp.route("/api/plam/coverage")
def api_plam_coverage():
    """PLAMカバレッジ統計（管理者用）"""
    pw = request.headers.get("X-Password", "")
    if not check_password(pw, "board"):
        return jsonify({"error": "unauthorized"}), 401

    con = get_con()
    try:
        cur = con.cursor()

        # 全体集計
        cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済'")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM award_books WHERE status='確認済' AND plam_work_id IS NOT NULL")
        linked = cur.fetchone()[0]

        # 賞別集計
        cur.execute("""
            SELECT award,
                   COUNT(*) AS total,
                   COUNT(plam_work_id) AS linked
            FROM award_books WHERE status='確認済'
            GROUP BY award ORDER BY award
        """)
        by_award = [{"award": r[0], "total": r[1], "linked": r[2]} for r in cur.fetchall()]

        # 未リンク作品（タイトル・賞・年）上位30件
        cur.execute("""
            SELECT title, author, award, award_year
            FROM award_books
            WHERE status='確認済' AND plam_work_id IS NULL
            ORDER BY award_year DESC NULLS LAST, award, title
            LIMIT 30
        """)
        unlinked = [{"title": r[0], "author": r[1], "award": r[2], "year": r[3]} for r in cur.fetchall()]

        return jsonify({
            "total": total,
            "linked": linked,
            "coverage": round(linked / total * 100, 1) if total else 0,
            "by_award": by_award,
            "unlinked_sample": unlinked,
        })
    finally:
        con.close()


@plam_bp.route("/api/plam/book")
def api_plam_book():
    """書籍タイトルからPLAM受賞情報を返す"""
    title = request.args.get("title", "").strip()
    author = request.args.get("author", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    info = get_book_plam_info(title, author)
    if info is None:
        return jsonify(None), 200
    return jsonify(info)

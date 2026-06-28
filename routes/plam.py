from flask import Blueprint, jsonify, render_template, request
from services.plam import get_award_network, get_bridge_works, get_book_plam_info, get_related_works

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

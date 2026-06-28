from flask import Blueprint, jsonify, render_template
from services.plam import get_award_network, get_bridge_works

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

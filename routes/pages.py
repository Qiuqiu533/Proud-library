from flask import Blueprint, render_template
from services.utils import auto_cleanup_images

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def index():
    return render_template("index.html")


@pages_bp.route("/reset-password")
def reset_password_page():
    """パスワードリセットページ（メールリンクから遷移）"""
    return render_template("index.html")


@pages_bp.route("/ping")
def ping():
    auto_cleanup_images()
    return "ok", 200

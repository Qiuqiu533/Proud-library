from flask import Blueprint, render_template, Response
from services.utils import auto_cleanup_images
from config import STATIC_VERSION

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def index():
    return render_template("index.html", static_version=STATIC_VERSION)


@pages_bp.route("/reset-password")
def reset_password_page():
    """パスワードリセットページ（メールリンクから遷移）"""
    return render_template("index.html", static_version=STATIC_VERSION)


@pages_bp.route("/robots.txt")
def robots_txt():
    """非公開アプリのため全クローラーを拒否"""
    content = "User-agent: *\nDisallow: /\n"
    return Response(content, mimetype="text/plain")


@pages_bp.route("/ping")
def ping():
    auto_cleanup_images()
    return "ok", 200

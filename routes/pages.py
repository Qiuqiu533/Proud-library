from flask import Blueprint, render_template, Response
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
    """外形監視・keep-alive専用の単純な死活確認。DBには一切接続しない
    （2026-07-21: 旧実装がDB接続を伴っていたため、外部監視の高頻度アクセスが
    Neonのアイドルタイマーを継続的にリセットし、Scale to Zeroを妨げていた）。"""
    return "ok", 200

import os
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask import Flask, request

_SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if _SENTRY_DSN:
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

app = Flask(__name__)

# ── Blueprint登録 ──────────────────────────────────────────────────────────
from routes.pages import pages_bp
from routes.auth import auth_bp
from routes.books import books_bp
from routes.awards import awards_bp
from routes.community import community_bp
from routes.user import user_bp
from routes.loans import loans_bp
from routes.admin import admin_bp
from routes.invite import invite_bp
from routes.events import events_bp
from routes.timeline import timeline_bp
from routes.newsletter import newsletter_bp
from routes.plam import plam_bp

app.register_blueprint(pages_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(books_bp)
app.register_blueprint(awards_bp)
app.register_blueprint(community_bp)
app.register_blueprint(user_bp)
app.register_blueprint(loans_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(invite_bp)
app.register_blueprint(events_bp)
app.register_blueprint(timeline_bp)
app.register_blueprint(newsletter_bp)
app.register_blueprint(plam_bp)

# ── DBコネクション自動返却 ────────────────────────────────────────────────
# get_con()のclose()忘れ・例外発生時の接続リークを防ぐため、
# リクエスト終了時に未closeの接続を強制的にプールへ返却する。
from database import close_request_connections

@app.teardown_appcontext
def _teardown_db(exception=None):
    close_request_connections()

# ── DB初期化・マイグレーション ──────────────────────────────────────────────
from migrations import _ensure_db
from services.books import _auto_classify_new_books

_ensure_db()
_auto_classify_new_books()   # バックグラウンドで週1回実行

@app.after_request
def set_security_headers(response):
    # 静的ファイルは1年キャッシュ（app.jsはSWでバージョン管理）
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com; "
        "img-src 'self' data: "
            "ndlsearch.ndl.go.jp "
            "images-na.ssl-images-amazon.com "
            "m.media-amazon.com "
            "covers.openlibrary.org "
            "books.google.com "
            "books.googleusercontent.com "
            "lh3.googleusercontent.com "
            "*.googleusercontent.com "
            "www.librarylife.net "
            "librarylife.net; "
        "connect-src 'self' *.ingest.us.sentry.io; "
        "frame-ancestors 'none';"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)

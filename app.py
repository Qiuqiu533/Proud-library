import os
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask import Flask

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

# ── DB初期化・マイグレーション ──────────────────────────────────────────────
from migrations import _ensure_db
from services.books import _auto_classify_new_books

_ensure_db()
_auto_classify_new_books()   # バックグラウンドで週1回実行

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)

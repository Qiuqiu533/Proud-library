from __future__ import annotations
import hashlib
import secrets as _secrets
import bcrypt
import threading
import logging
from typing import Any

logger = logging.getLogger(__name__)
import time
from collections import defaultdict

from flask import request, jsonify
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import KEYWORD_GENRE, NDC_TO_GENRE, _RESEND_API_KEY, _APP_BASE_URL, \
    _BREVO_SMTP_PASSWORD, _BREVO_SMTP_USER, _NOTIFY_FROM_EMAIL
from database import get_con, execute, fetchone, USE_PG
import requests as _requests

# ── レートリミット ─────────────────────────────────────────────────────────
_rate_store = defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(key: str, limit: int = 5, window: int = 60) -> bool:
    """True=通過OK, False=制限超過。key単位でwindow秒間にlimit回まで許可。"""
    now = time.time()
    with _rate_lock:
        timestamps = _rate_store[key]
        timestamps[:] = [t for t in timestamps if now - t < window]
        if len(timestamps) >= limit:
            return False
        timestamps.append(now)
        return True


def rate_limit(limit=5, window=60):
    """デコレータ: IPアドレス＋エンドポイントでレートリミット"""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
            key = f"{ip}:{f.__name__}"
            if not _check_rate_limit(key, limit, window):
                return jsonify({"error": "しばらく時間をおいてから再試行してください"}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator


def _hira_to_kata(s: str) -> str:
    return "".join(chr(ord(c) + 96) if "ぁ" <= c <= "ゖ" else c for c in (s or ""))


def _kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in (s or ""))


def _ndc_to_genre(ndc: str) -> str:
    if not ndc:
        return ""
    for length in [4, 3, 2]:
        prefix = ndc[:length]
        if prefix in NDC_TO_GENRE:
            return NDC_TO_GENRE[prefix]
    return ""


def _keyword_genre(title: str, author: str = "") -> str:
    text = (title or "") + " " + (author or "")
    for keywords, genre in KEYWORD_GENRE:
        if any(kw in text for kw in keywords):
            return genre
    return ""


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """bcrypt でハッシュ化。戻り値は (hash, "") — salt は bcrypt が内包するため空文字。"""
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
    return hashed.decode(), ""


def _verify_password(password: str, password_hash: str, salt: str) -> bool:
    """bcrypt ハッシュ（$2b$）と旧 SHA-256 ハッシュの両方を検証する。"""
    if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    # 旧 SHA-256 方式（後方互換）
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return h == password_hash


def _is_bcrypt_hash(password_hash: str) -> bool:
    """bcrypt ハッシュかどうか判定する。"""
    return password_hash.startswith("$2b$") or password_hash.startswith("$2a$")


def _send_email_brevo(to_email: str, subject: str, body: str) -> bool:
    """Brevo SMTP でメール送信。未設定なら False を返す。"""
    if not _BREVO_SMTP_PASSWORD or not _BREVO_SMTP_USER:
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = _NOTIFY_FROM_EMAIL or _BREVO_SMTP_USER
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP("smtp-relay.brevo.com", 587) as server:
            server.starttls()
            server.login(_BREVO_SMTP_USER, _BREVO_SMTP_PASSWORD)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        return True
    except Exception as e:
        logger.error("Brevo send error: %s", e)
        return False


def _send_reset_email(to_email, room, token):
    reset_url = f"{_APP_BASE_URL}/reset-password?token={token}"
    body = f"""プラウド船橋 コミュニティ図書館

パスワードリセットのご依頼を受け付けました。

下記のURLをクリックして、新しいパスワードを設定してください。
（このリンクは30分間有効です）

{reset_url}

このメールに心当たりがない場合は、そのまま無視してください。

─────────────────────────
プラウド船橋 コミュニティ図書館
"""
    subject = "【プラウド船橋図書館】パスワードリセット"

    # Brevo SMTP を優先
    if _BREVO_SMTP_PASSWORD and _BREVO_SMTP_USER:
        return _send_email_brevo(to_email, subject, body)

    # フォールバック: Resend API
    if _RESEND_API_KEY:
        try:
            res = _requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": "図書館 <onboarding@resend.dev>", "to": [to_email], "subject": subject, "text": body},
                timeout=10
            )
            return res.status_code == 200
        except Exception as e:
            logger.error("Resend error: %s", e)
            return False

    logger.warning("メール設定なし（BREVO_SMTP_PASSWORD/RESEND_API_KEY 未設定）")
    return False


def auto_cleanup_images():
    """DB使用量が95%超の場合、古い画像データを自動削除する"""
    if not USE_PG:
        return
    try:
        con = get_con()
        size_row = fetchone(con, "SELECT pg_database_size(current_database()) AS bytes")
        total_bytes = size_row["bytes"]
        limit_bytes = 512 * 1024 * 1024
        percent = total_bytes / limit_bytes * 100
        if percent >= 95:
            execute(con, """
                UPDATE staff_chat SET image_data = ''
                WHERE image_data != '' AND id IN (
                    SELECT id FROM staff_chat WHERE image_data != ''
                    ORDER BY created_at ASC LIMIT 50
                )
            """)
            execute(con, """
                UPDATE announcements SET image_url = ''
                WHERE image_url LIKE 'data:%' AND id IN (
                    SELECT id FROM announcements WHERE image_url LIKE 'data:%'
                    ORDER BY id ASC LIMIT 10
                )
            """)
            con.commit()
        con.close()
    except Exception as e:
        logger.error(f"auto_cleanup_images error: %s", e)
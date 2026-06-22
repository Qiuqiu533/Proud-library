import hashlib
import secrets as _secrets
import bcrypt
import threading
import time
from collections import defaultdict

from flask import request, jsonify
from config import KEYWORD_GENRE, NDC_TO_GENRE, _RESEND_API_KEY, _APP_BASE_URL
from database import get_con, execute, fetchone, USE_PG
import requests as _requests

# ── レートリミット ─────────────────────────────────────────────────────────
_rate_store = defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(key, limit=5, window=60):
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


def _hira_to_kata(s):
    return "".join(chr(ord(c) + 96) if "ぁ" <= c <= "ゖ" else c for c in (s or ""))


def _kata_to_hira(s):
    return "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in (s or ""))


def _ndc_to_genre(ndc):
    if not ndc:
        return ""
    for length in [4, 3, 2]:
        prefix = ndc[:length]
        if prefix in NDC_TO_GENRE:
            return NDC_TO_GENRE[prefix]
    return ""


def _keyword_genre(title, author=""):
    text = (title or "") + " " + (author or "")
    for keywords, genre in KEYWORD_GENRE:
        if any(kw in text for kw in keywords):
            return genre
    return ""


def _hash_password(password, salt=None):
    """bcrypt でハッシュ化。戻り値は (hash, "") — salt は bcrypt が内包するため空文字。"""
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
    return hashed.decode(), ""


def _verify_password(password, password_hash, salt):
    """bcrypt ハッシュ（$2b$）と旧 SHA-256 ハッシュの両方を検証する。"""
    if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    # 旧 SHA-256 方式（後方互換）
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return h == password_hash


def _is_bcrypt_hash(password_hash: str) -> bool:
    """bcrypt ハッシュかどうか判定する。"""
    return password_hash.startswith("$2b$") or password_hash.startswith("$2a$")


def _send_reset_email(to_email, room, token):
    if not _RESEND_API_KEY:
        return False
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
    try:
        res = _requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": "図書館 <onboarding@resend.dev>", "to": [to_email], "subject": "【プラウド船橋図書館】パスワードリセット", "text": body},
            timeout=10
        )
        return res.status_code == 200
    except Exception as e:
        print(f"email send error: {e}")
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
        print(f"auto_cleanup_images error: {e}")

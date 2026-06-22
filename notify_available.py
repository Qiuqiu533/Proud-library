"""
空き待ち通知スクリプト
GitHub Actions から毎日深夜2時（JST）に実行される。

必要な環境変数:
  DATABASE_URL        — Neon PostgreSQL 接続文字列
  BREVO_SMTP_PASSWORD — Brevo SMTP パスワード
  NOTIFY_FROM_EMAIL   — 送信元メールアドレス（Brevo で認証済みのもの）
  APP_BASE_URL        — アプリURL（メール内リンク用）例: https://proud-library.onrender.com
"""
from __future__ import annotations

import os
import sys
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL       = os.environ["DATABASE_URL"]
SMTP_PASSWORD      = os.environ["BREVO_SMTP_PASSWORD"]
FROM_EMAIL         = os.environ.get("NOTIFY_FROM_EMAIL", "noreply@proud-library.jp")
APP_BASE_URL       = os.environ.get("APP_BASE_URL", "https://proud-library.onrender.com")
BREVO_SMTP_HOST    = "smtp-relay.brevo.com"
BREVO_SMTP_PORT    = 587
BREVO_SMTP_USER    = os.environ.get("BREVO_SMTP_USER", FROM_EMAIL)


def get_con():
    con = psycopg2.connect(DATABASE_URL)
    con.cursor_factory = psycopg2.extras.RealDictCursor
    return con


def fetch_targets(con) -> list[dict]:
    """通知すべきレコードを返す。
    条件:
      - wish_list.notify = TRUE
      - availability_cache.status = 'available'
      - wish_list.notified_at IS NULL
        OR wish_list.notified_at < availability_cache.updated_at
        （新たに在庫可になったタイミングより前にしか通知していない）
    """
    sql = """
        SELECT
            w.room,
            w.isbn,
            u.email,
            g.title,
            g.author
        FROM wish_list w
        JOIN availability_cache a ON a.isbn = w.isbn
        LEFT JOIN user_accounts u ON u.room = w.room
        LEFT JOIN genre_books g ON g.isbn = w.isbn
        WHERE w.notify = TRUE
          AND a.status = 'available'
          AND (w.notified_at IS NULL OR w.notified_at < a.updated_at)
          AND u.email IS NOT NULL
          AND u.email <> ''
        ORDER BY w.isbn, w.room
    """
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def mark_notified(con, room: str, isbn: str) -> None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE wish_list SET notified_at = NOW() WHERE room = %s AND isbn = %s",
            (room, isbn),
        )
    con.commit()


def build_email(to: str, title: str, author: str, isbn: str) -> MIMEMultipart:
    book_label = f"『{title}』" if title else f"ISBN:{isbn}"
    author_line = f"　著者：{author}" if author else ""
    app_url = APP_BASE_URL

    subject = f"【プラウド船橋図書館】{book_label} が返却されました"
    body = f"""\
プラウド船橋コミュニティ図書館 貸出状況通知

{book_label}{author_line} が現在貸出可能になりました。

アプリから蔵書検索でご確認ください。
{app_url}

──────────────────────────
この通知はウィッシュリストに登録された本が
返却されたときに自動送信されます。
通知を停止するには、アプリのウィッシュリスト画面から
該当の本の 🔔 をタップしてオフにしてください。
──────────────────────────
プラウド船橋コミュニティ図書館
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to
    msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg


def send_email(msg: MIMEMultipart) -> bool:
    try:
        with smtplib.SMTP(BREVO_SMTP_HOST, BREVO_SMTP_PORT) as server:
            server.starttls()
            server.login(BREVO_SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())
        return True
    except Exception as e:
        logger.error("メール送信失敗 to=%s: %s", msg["To"], e)
        return False


def main() -> None:
    con = get_con()
    targets = fetch_targets(con)
    logger.info("通知対象: %d 件", len(targets))

    sent = 0
    skipped = 0
    for row in targets:
        email = row["email"]
        room  = row["room"]
        isbn  = row["isbn"]
        title  = row.get("title") or ""
        author = row.get("author") or ""

        msg = build_email(email, title, author, isbn)
        if send_email(msg):
            mark_notified(con, room, isbn)
            logger.info("送信完了: room=%s isbn=%s -> %s", room, isbn, email)
            sent += 1
        else:
            skipped += 1

    con.close()
    logger.info("完了: 送信=%d, 失敗=%d", sent, skipped)
    if skipped > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

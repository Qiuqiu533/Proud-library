"""
返却リマインダースクリプト
GitHub Actions から毎日実行される。

対象: my_loans（住民が自己申告で登録した「借りている本」）のうち
  - 返却期限の3日前
  - 返却期限当日
  - 返却期限を過ぎている（延滞）
のいずれかに該当し、まだ本日リマインドを送っていないもの。

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
from datetime import date
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
    """リマインド対象を返す。
    条件:
      - 未返却（returned_at IS NULL）
      - 返却期限が3日以内（当日・延滞含む）
      - 本日まだリマインドを送っていない（reminder_sent_at が今日より前 or NULL）
    """
    sql = """
        SELECT
            m.id, m.room, m.isbn, m.title, m.author, m.due_date,
            u.email
        FROM my_loans m
        LEFT JOIN user_accounts u ON u.room = m.room
        WHERE m.returned_at IS NULL
          AND m.due_date <= CURRENT_DATE + INTERVAL '3 days'
          AND (m.reminder_sent_at IS NULL OR m.reminder_sent_at::date < CURRENT_DATE)
          AND u.email IS NOT NULL
          AND u.email <> ''
        ORDER BY m.due_date ASC
    """
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def mark_reminded(con, loan_id: int) -> None:
    with con.cursor() as cur:
        cur.execute("UPDATE my_loans SET reminder_sent_at = NOW() WHERE id = %s", (loan_id,))
    con.commit()


def build_email(to: str, title: str, author: str, isbn: str, due_date: date) -> MIMEMultipart:
    book_label = f"『{title}』" if title else f"ISBN:{isbn}"
    author_line = f"　著者：{author}" if author else ""
    today = date.today()
    days_left = (due_date - today).days

    if days_left > 0:
        status_line = f"返却期限まであと{days_left}日です（期限: {due_date.strftime('%Y年%m月%d日')}）。"
        subject = f"【プラウド船橋図書館】返却期限のお知らせ（あと{days_left}日）"
    elif days_left == 0:
        status_line = f"本日が返却期限です（{due_date.strftime('%Y年%m月%d日')}）。"
        subject = "【プラウド船橋図書館】本日が返却期限です"
    else:
        overdue_days = -days_left
        status_line = f"返却期限（{due_date.strftime('%Y年%m月%d日')}）を{overdue_days}日過ぎています。"
        subject = f"【プラウド船橋図書館】返却期限超過のお知らせ（{overdue_days}日超過）"

    body = f"""\
プラウド船橋コミュニティ図書館 返却リマインダー

{book_label}{author_line}

{status_line}

お手数ですが、早めのご返却にご協力をお願いいたします。

──────────────────────────
このメールはアプリで「借り中」として登録した本の
返却期限が近い・過ぎている場合に自動送信されます。
返却済みの場合は、アプリの読書記録から
ステータスを変更（解除）してください。
{APP_BASE_URL}
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
    logger.info("リマインド対象: %d 件", len(targets))

    sent = 0
    skipped = 0
    for row in targets:
        email    = row["email"]
        loan_id  = row["id"]
        isbn     = row["isbn"]
        title    = row.get("title") or ""
        author   = row.get("author") or ""
        due_date = row["due_date"]

        msg = build_email(email, title, author, isbn, due_date)
        if send_email(msg):
            mark_reminded(con, loan_id)
            logger.info("送信完了: loan_id=%s isbn=%s -> %s", loan_id, isbn, email)
            sent += 1
        else:
            skipped += 1

    con.close()
    logger.info("完了: 送信=%d, 失敗=%d", sent, skipped)
    if skipped > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

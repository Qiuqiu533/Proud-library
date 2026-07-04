"""
返却リマインダースクリプト（段階的督促対応）
GitHub Actions から毎日実行される。

対象: my_loans（住民が自己申告で登録した「借りている本」）のうち
  - 返却期限の3日前〜当日: 毎日1回、穏やかな予告文面
  - 延滞1〜6日: 3日おきに、通常の督促文面
  - 延滞7〜13日: 2日おきに、やや強めの督促文面
  - 延滞14日以上: 毎日、強い督促文面

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
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
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
    """リマインド候補を返す（送信すべきかの最終判定はPython側のshould_remind_todayで行う）。
    条件: 未返却（returned_at IS NULL）・返却期限が3日以内（当日・延滞含む）・メール登録済み
    """
    sql = """
        SELECT
            m.id, m.room, m.isbn, m.title, m.author, m.due_date, m.reminder_sent_at,
            u.email
        FROM my_loans m
        LEFT JOIN user_accounts u ON u.room = m.room
        WHERE m.returned_at IS NULL
          AND m.due_date <= CURRENT_DATE + INTERVAL '3 days'
          AND u.email IS NOT NULL
          AND u.email <> ''
        ORDER BY m.due_date ASC
    """
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def should_remind_today(due_date: date, reminder_sent_at) -> bool:
    """延滞日数に応じた送信間隔で、本日送るべきかを判定する。
    予告〜当日: 毎日／延滞1-6日: 3日おき／延滞7-13日: 2日おき／延滞14日以上: 毎日
    """
    if reminder_sent_at is None:
        return True
    last_sent_date = reminder_sent_at.date() if hasattr(reminder_sent_at, "date") else reminder_sent_at
    days_since_last = (date.today() - last_sent_date).days
    if days_since_last <= 0:
        return False
    days_left = (due_date - date.today()).days
    if days_left >= 0:
        return True
    overdue_days = -days_left
    if overdue_days <= 6:
        return days_since_last >= 3
    elif overdue_days <= 13:
        return days_since_last >= 2
    return True


def mark_reminded(con, loan_id: int) -> None:
    with con.cursor() as cur:
        cur.execute("UPDATE my_loans SET reminder_sent_at = NOW() WHERE id = %s", (loan_id,))
    con.commit()


def build_email(to: str, title: str, author: str, isbn: str, due_date: date) -> MIMEMultipart:
    book_label = f"『{title}』" if title else f"ISBN:{isbn}"
    author_line = f"　著者：{author}" if author else ""
    today = date.today()
    days_left = (due_date - today).days
    due_str = due_date.strftime("%Y年%m月%d日")

    if days_left > 0:
        subject = f"【プラウド船橋図書館】返却期限のお知らせ（あと{days_left}日）"
        status_line = f"返却期限まであと{days_left}日です（期限: {due_str}）。"
        closing = "お手数ですが、期限までのご返却にご協力をお願いいたします。"
    elif days_left == 0:
        subject = "【プラウド船橋図書館】本日が返却期限です"
        status_line = f"本日が返却期限です（{due_str}）。"
        closing = "お手数ですが、本日中のご返却にご協力をお願いいたします。"
    else:
        overdue_days = -days_left
        if overdue_days <= 6:
            subject = f"【プラウド船橋図書館】返却期限超過のお知らせ（{overdue_days}日超過）"
            status_line = f"返却期限（{due_str}）を{overdue_days}日過ぎています。"
            closing = "お手数ですが、早めのご返却にご協力をお願いいたします。"
        elif overdue_days <= 13:
            subject = f"【プラウド船橋図書館】返却のお願い（{overdue_days}日超過）"
            status_line = f"返却期限（{due_str}）を{overdue_days}日過ぎており、他の住民の方もこの本を待っている可能性があります。"
            closing = "恐れ入りますが、なるべく早めのご返却をお願いいたします。返却済みの場合は、アプリでステータスの変更をお願いいたします。"
        else:
            subject = f"【プラウド船橋図書館】重要：返却のお願い（{overdue_days}日超過）"
            status_line = f"返却期限（{due_str}）を{overdue_days}日過ぎています。長期延滞となっております。"
            closing = "他の住民の方が読めない状態が続いております。至急のご返却にご協力をお願いいたします。ご事情がある場合は理事会までご連絡ください。"

    body = f"""\
プラウド船橋コミュニティ図書館 返却リマインダー

{book_label}{author_line}

{status_line}

{closing}

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
    candidates = fetch_targets(con)
    targets = [row for row in candidates if should_remind_today(row["due_date"], row.get("reminder_sent_at"))]
    logger.info("リマインド候補: %d 件 / 本日送信対象: %d 件", len(candidates), len(targets))

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

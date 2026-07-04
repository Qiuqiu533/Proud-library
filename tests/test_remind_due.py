"""remind_due.py の純粋ロジック（DB・SMTP接続なしの部分）のテスト"""
import os
import sys
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("BREVO_SMTP_PASSWORD", "test")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import remind_due  # noqa: E402


def test_should_remind_today_no_previous_reminder():
    """一度もリマインドしていない場合は常に送る"""
    assert remind_due.should_remind_today(date.today(), None) is True


def test_should_remind_today_already_sent_today():
    """本日すでに送信済みなら送らない"""
    from datetime import datetime
    now = datetime.now()
    assert remind_due.should_remind_today(date.today(), now) is False


def test_should_remind_today_before_due_sends_daily():
    """期限前（予告〜当日）は毎日送ってよい"""
    from datetime import datetime
    yesterday_dt = datetime.now() - timedelta(days=1)
    due = date.today() + timedelta(days=2)
    assert remind_due.should_remind_today(due, yesterday_dt) is True


def test_should_remind_today_overdue_1_6_days_every_3_days():
    """延滞1〜6日は3日おき"""
    from datetime import datetime
    due = date.today() - timedelta(days=3)
    sent_1_day_ago = datetime.now() - timedelta(days=1)
    sent_3_days_ago = datetime.now() - timedelta(days=3)
    assert remind_due.should_remind_today(due, sent_1_day_ago) is False
    assert remind_due.should_remind_today(due, sent_3_days_ago) is True


def test_should_remind_today_overdue_7_13_days_every_2_days():
    """延滞7〜13日は2日おき"""
    from datetime import datetime
    due = date.today() - timedelta(days=10)
    sent_1_day_ago = datetime.now() - timedelta(days=1)
    sent_2_days_ago = datetime.now() - timedelta(days=2)
    assert remind_due.should_remind_today(due, sent_1_day_ago) is False
    assert remind_due.should_remind_today(due, sent_2_days_ago) is True


def test_should_remind_today_overdue_14_plus_days_daily():
    """延滞14日以上は毎日"""
    from datetime import datetime
    due = date.today() - timedelta(days=20)
    sent_1_day_ago = datetime.now() - timedelta(days=1)
    assert remind_due.should_remind_today(due, sent_1_day_ago) is True


def test_build_email_before_due():
    msg = remind_due.build_email("test@example.com", "テスト本", "著者", "9784000000001", date.today() + timedelta(days=2))
    assert "あと2日" in msg["Subject"]


def test_build_email_due_today():
    msg = remind_due.build_email("test@example.com", "テスト本", "著者", "9784000000001", date.today())
    assert "本日が返却期限" in msg["Subject"]


def test_build_email_overdue_mild():
    msg = remind_due.build_email("test@example.com", "テスト本", "著者", "9784000000001", date.today() - timedelta(days=3))
    assert "超過のお知らせ" in msg["Subject"]
    assert "3日超過" in msg["Subject"]


def test_build_email_overdue_medium():
    msg = remind_due.build_email("test@example.com", "テスト本", "著者", "9784000000001", date.today() - timedelta(days=10))
    assert "返却のお願い" in msg["Subject"]
    assert "重要" not in msg["Subject"]


def test_build_email_overdue_severe():
    msg = remind_due.build_email("test@example.com", "テスト本", "著者", "9784000000001", date.today() - timedelta(days=20))
    assert "重要" in msg["Subject"]

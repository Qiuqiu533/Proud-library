"""管理者操作ログ記録ヘルパー"""
from __future__ import annotations
import logging
from flask import request
from database import get_con, execute, USE_PG

logger = logging.getLogger(__name__)


def log_action(action: str, target: str = "", detail: str = "") -> None:
    """管理操作を audit_log に非同期で記録する（失敗してもメイン処理は止めない）"""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    if ip:
        ip = ip.split(",")[0].strip()[:45]
    try:
        con = get_con()
        if USE_PG:
            execute(con, """
                INSERT INTO audit_log (action, target, detail, ip)
                VALUES (%s, %s, %s, %s)
            """, (action[:100], target[:200], detail[:500], ip))
        else:
            execute(con, """
                INSERT INTO audit_log (action, target, detail, ip)
                VALUES (?, ?, ?, ?)
            """, (action[:100], target[:200], detail[:500], ip))
        con.commit()
        con.close()
    except Exception as e:
        logger.error("audit_log 記録失敗: %s", e)

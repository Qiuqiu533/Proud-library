"""ISBN整合性監査（genre_books vs OpenBD）。

2026-07-05: ISBN 9784488029364 が genre_books では「すごい科学論文」（誤り）の
まま登録されており、librarylife.net・OpenBDでは「カフェーの帰り道」（正しい）
と判明した事故を受けて追加。「未登録のみ追加」の通常同期ではこのような
既存データの破損を検知・修復できないため、別途の監査・修復の仕組みを用意する。

自動修復はしない（OpenBD側にも稀に誤りがあり、自動上書きすると逆に壊す
リスクがあるため）。検出→ログ→管理画面表示→管理者確認→修復、という
フローに限定する。
"""
import logging
import unicodedata
import time
from difflib import SequenceMatcher

import requests

logger = logging.getLogger(__name__)

from config import OPENBD_API
from database import get_con, db_session, execute, fetchall, fetchone, USE_PG

_audit_running = False


def is_audit_running():
    return _audit_running


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def _sim(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _mismatch_fields(db_title, db_author, ob_title, ob_author):
    """タイトル・著者のどちらが不一致かを判定する。表記ゆれ（副題・スペース等）
    による誤検知を避けるため、閾値は緩め（0.4未満のみ「明確な不一致」とする）。"""
    fields = []
    if ob_title and _sim(db_title, ob_title) < 0.4:
        fields.append("title")
    if ob_author and db_author and _sim(db_author, ob_author) < 0.4:
        fields.append("author")
    return fields


def run_integrity_audit(force=False, limit=None):
    """genre_books全件（またはlimit件）をOpenBDと突き合わせ、明確な不一致を
    integrity_findingsに記録する。バックグラウンドスレッドで実行想定。"""
    import threading

    def _run():
        global _audit_running
        if _audit_running:
            logger.info("整合性監査: 既に実行中のためスキップ")
            return
        _audit_running = True
        checked = 0
        found = 0
        try:
            con = get_con()
            sql = "SELECT isbn, title, author, publisher FROM genre_books WHERE isbn IS NOT NULL AND isbn != ''"
            if limit:
                sql += f" LIMIT {int(limit)}"
            rows = fetchall(con, sql)
            con.close()

            batch_size = 20
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                isbns = [r["isbn"] for r in batch]
                try:
                    resp = requests.get(OPENBD_API, params={"isbn": ",".join(isbns)}, timeout=15)
                    ob_list = resp.json()
                except Exception as e:
                    logger.info(f"整合性監査: OpenBDバッチエラー {e}")
                    continue

                for r, ob in zip(batch, ob_list):
                    checked += 1
                    if not ob:
                        continue
                    summary = ob.get("summary", {}) or {}
                    ob_title = summary.get("title", "")
                    ob_author = summary.get("author", "")
                    ob_publisher = summary.get("publisher", "")
                    if not ob_title:
                        continue
                    fields = _mismatch_fields(r["title"], r["author"], ob_title, ob_author)
                    if fields:
                        found += 1
                        _save_finding(r["isbn"], r["title"], r["author"], r["publisher"],
                                      ob_title, ob_author, ob_publisher, fields)
                    else:
                        _clear_finding(r["isbn"])
                time.sleep(0.5)

            logger.info(f"整合性監査: 完了（{checked}件チェック、{found}件の不一致を検出）")
        except Exception as e:
            logger.error(f"整合性監査エラー: {e}", exc_info=True)
        finally:
            _audit_running = False

    threading.Thread(target=_run, daemon=True).start()


def _save_finding(isbn, db_title, db_author, db_publisher, ob_title, ob_author, ob_publisher, fields):
    try:
        with db_session() as con:
            if USE_PG:
                execute(con, """
                    INSERT INTO integrity_findings
                        (isbn, db_title, db_author, db_publisher, openbd_title, openbd_author, openbd_publisher, mismatch_fields, checked_at, resolved)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),FALSE)
                    ON CONFLICT (isbn) DO UPDATE SET
                        db_title=EXCLUDED.db_title, db_author=EXCLUDED.db_author, db_publisher=EXCLUDED.db_publisher,
                        openbd_title=EXCLUDED.openbd_title, openbd_author=EXCLUDED.openbd_author, openbd_publisher=EXCLUDED.openbd_publisher,
                        mismatch_fields=EXCLUDED.mismatch_fields, checked_at=NOW(), resolved=FALSE
                """, (isbn, db_title, db_author, db_publisher, ob_title, ob_author, ob_publisher, ",".join(fields)))
            else:
                execute(con, """
                    INSERT OR REPLACE INTO integrity_findings
                        (isbn, db_title, db_author, db_publisher, openbd_title, openbd_author, openbd_publisher, mismatch_fields, checked_at, resolved)
                    VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,0)
                """, (isbn, db_title, db_author, db_publisher, ob_title, ob_author, ob_publisher, ",".join(fields)))
            con.commit()
    except Exception as e:
        logger.error(f"整合性監査: finding保存エラー {isbn}: {e}")


def _clear_finding(isbn):
    """再チェックで一致した場合、未解決のfindingがあれば削除する（解決済みの履歴は
    integrity_logに残っているのでここでは消して問題ない）。"""
    try:
        with db_session() as con:
            ph = "%s" if USE_PG else "?"
            execute(con, f"DELETE FROM integrity_findings WHERE isbn={ph} AND resolved={'FALSE' if USE_PG else '0'}", (isbn,))
            con.commit()
    except Exception as e:
        logger.error(f"整合性監査: finding削除エラー {isbn}: {e}")


def repair_finding(isbn, fields, operator):
    """管理者が承認したフィールドのみ、OpenBDの値でgenre_booksを上書きし、
    integrity_logに履歴を残す。"""
    con = get_con()
    try:
        finding = fetchone(con, "SELECT * FROM integrity_findings WHERE isbn=%s" if USE_PG else
                            "SELECT * FROM integrity_findings WHERE isbn=?", (isbn,))
        if not finding:
            con.close()
            return {"error": "finding not found"}, 404

        col_map = {"title": ("db_title", "openbd_title"), "author": ("db_author", "openbd_author"),
                   "publisher": ("db_publisher", "openbd_publisher")}
        updates = {}
        for f in fields:
            if f not in col_map:
                continue
            before_col, after_col = col_map[f]
            before_val = finding[before_col]
            after_val = finding[after_col]
            updates[f] = (before_val, after_val)

        if not updates:
            con.close()
            return {"error": "no valid fields"}, 400

        cur = con.cursor()
        set_clause = ", ".join(f"{f}=%s" if USE_PG else f"{f}=?" for f in updates)
        ph = "%s" if USE_PG else "?"
        cur.execute(f"UPDATE genre_books SET {set_clause} WHERE isbn={ph}",
                    tuple(v[1] for v in updates.values()) + (isbn,))
        for f, (before_val, after_val) in updates.items():
            cur.execute(
                f"INSERT INTO integrity_log (isbn, field, before_value, after_value, operator, reason) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                (isbn, f, before_val, after_val, operator, "管理者承認による整合性修復")
            )
        cur.execute(f"UPDATE integrity_findings SET resolved={'TRUE' if USE_PG else '1'} WHERE isbn={ph}", (isbn,))
        con.commit()
        con.close()
        return {"ok": True, "updated_fields": list(updates.keys())}, 200
    except Exception as e:
        logger.error(f"整合性修復エラー {isbn}: {e}", exc_info=True)
        try:
            con.rollback()
        except Exception:
            pass
        con.close()
        return {"error": str(e)}, 500

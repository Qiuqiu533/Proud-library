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
import re
import unicodedata
import time
from difflib import SequenceMatcher

import requests

logger = logging.getLogger(__name__)

from config import OPENBD_API
from database import get_con, db_session, execute, fetchall, fetchone, USE_PG

_audit_running = False

# 末尾の「（朝日文庫）」「〈3〉」「Vol.2」「【新版】」等、シリーズ名・レーベル名・
# 巻数・版表記を除去してから比較する（genre_books側は表示用に長いタイトルを
# 保持する設計のため、素の文字列類似度では大量に誤検知するとの指摘を受けて
# 2026-07-06に追加）。
_TITLE_NOISE_RE = re.compile(
    r"[\s]*[（(【\[〈<][^（）()【】\[\]〈〉<>]*[）)】\]〉>]\s*$"
)
_TITLE_VOL_SUFFIX_RE = re.compile(r"[\s]*(vol\.?\s*\d+|第?\d+巻|[（(]?[上下][）)]?)\s*$", re.IGNORECASE)
# OpenBDの著者欄は「姓,名,生没年 姓,名,生没年 ほか」のように複数人を空白区切りで
# 連結している。生没年・「ほか」を除去してから人物単位に分割する。
_AUTHOR_YEAR_RE = re.compile(r",?\d{4}-\d{0,4}")
_AUTHOR_ETC_RE = re.compile(r"ほか\s*$")


def is_audit_running():
    return _audit_running


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def _sim(a, b):
    return SequenceMatcher(None, a, b).ratio()


def _dense(s):
    """空白・カンマを除去し、大文字小文字を統一して比較用に文字列を圧縮する
    （例: '1Q84 BOOK 2' と '1Q84...book2...' のような大文字小文字差を吸収）。"""
    return re.sub(r"[\s,、]", "", (s or "").lower())


def _normalize_title_for_compare(title):
    """タイトル末尾のシリーズ名・レーベル名・巻数・版表記を繰り返し除去する。
    例: '悪人（上）（朝日文庫）' → '悪人'、'魔球 (講談社文庫)' → '魔球'"""
    s = _norm(title)
    prev = None
    while prev != s:
        prev = s
        s = _TITLE_NOISE_RE.sub("", s)
        s = _TITLE_VOL_SUFFIX_RE.sub("", s)
    return _dense(s)


def _title_mismatch(db_title, ob_title):
    if not ob_title:
        return False
    a, b = _normalize_title_for_compare(db_title), _normalize_title_for_compare(ob_title)
    if not a or not b:
        return False
    if len(a) >= 2 and (a in b or b in a):
        return False
    return _sim(a, b) < 0.5


def _author_tokens(ob_author):
    """OpenBDの著者欄（複数人・生没年付き）を人物単位のトークンに分割する。"""
    s = _norm(ob_author)
    s = _AUTHOR_ETC_RE.sub("", s)
    s = _AUTHOR_YEAR_RE.sub("", s)
    return [_dense(t) for t in s.split() if _dense(t)]


def _author_mismatch(db_author, ob_author):
    if not ob_author or not db_author:
        return False
    db_dense = _dense(_norm(db_author))
    if not db_dense:
        return False
    for token in _author_tokens(ob_author):
        if not token:
            continue
        if len(token) >= 2 and (token in db_dense or db_dense in token):
            return False
        if _sim(db_dense, token) >= 0.6:
            return False
    return True


def _mismatch_fields(db_title, db_author, ob_title, ob_author):
    """タイトル・著者のどちらが不一致かを判定する。genre_books側はシリーズ名・
    文庫レーベル・巻数を含む表示用タイトルを保持し、OpenBD側は複数著者を
    生没年付きで列挙する設計のため、双方を正規化・分割してから比較する
    （2026-07-06改修：素の文字列類似度比較では誤検知が9割超だったため）。"""
    fields = []
    if _title_mismatch(db_title, ob_title):
        fields.append("title")
    if _author_mismatch(db_author, ob_author):
        fields.append("author")
    return fields


def severity_info(mismatch_fields):
    """実データ検証の結果、タイトル・著者とも不一致はほぼ100%が本物の誤登録、
    著者のみ不一致はほぼ100%が表記ゆれ（誤検知）だったため（2026-07-06）、
    mismatch_fieldsの組み合わせから重要度を判定する。修復優先度スコアは
    タイトル不一致+50・著者不一致+30・OpenBD取得成功+20・ISBN一致+10を基準に、
    ここまで監査に到達している時点でOpenBD取得・ISBN一致は常に真なので
    base=30固定とする。"""
    fields = set(mismatch_fields) if isinstance(mismatch_fields, (list, set)) else set(
        (mismatch_fields or "").split(","))
    fields.discard("")
    base = 30
    score = base + (50 if "title" in fields else 0) + (30 if "author" in fields else 0)
    score = min(score, 100)
    if "title" in fields and "author" in fields:
        level = "critical"
    elif "title" in fields:
        level = "warning"
    elif "author" in fields:
        level = "info"
    else:
        level = "info"
    return {"level": level, "score": score}


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

            _save_audit_time(checked, found)
            logger.info(f"整合性監査: 完了（{checked}件チェック、{found}件の不一致を検出）")
        except Exception as e:
            logger.error(f"整合性監査エラー: {e}", exc_info=True)
        finally:
            _audit_running = False

    threading.Thread(target=_run, daemon=True).start()


def _save_audit_time(checked, found):
    import datetime
    now = datetime.datetime.now().isoformat()
    try:
        con = get_con()
        if USE_PG:
            execute(con,
                "INSERT INTO settings (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                ("integrity_audit_last_run", now))
        else:
            execute(con,
                "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                ("integrity_audit_last_run", now))
        con.commit(); con.close()
    except Exception as e:
        logger.error(f"_save_audit_time error: %s", e)


def dashboard_summary():
    """データ健全性ダッシュボード用の集計値をまとめて返す。"""
    from config import get_setting
    con = get_con()
    try:
        unresolved = fetchall(
            con,
            "SELECT mismatch_fields FROM integrity_findings WHERE resolved=%s" if USE_PG
            else "SELECT mismatch_fields FROM integrity_findings WHERE resolved=0",
            (False,) if USE_PG else ()
        )
        counts = {"critical": 0, "warning": 0, "info": 0}
        for r in unresolved:
            level = severity_info(r["mismatch_fields"])["level"]
            counts[level] = counts.get(level, 0) + 1

        total_row = fetchone(con, "SELECT COUNT(*) as cnt FROM genre_books")
        total_books = total_row["cnt"] if total_row else 0

        resolved_row = fetchall(con, "SELECT DISTINCT isbn FROM integrity_log")
        resolved_count = len(resolved_row)
    finally:
        con.close()

    total_unresolved = sum(counts.values())
    # 健全性スコア: 全蔵書に対する「未解決かつ本物の可能性が高い(critical)」件数の割合から算出。
    # warning/infoは表記ゆれ等を含むため軽い重み付けに留める。
    if total_books:
        penalty = (counts["critical"] * 1.0 + counts["warning"] * 0.3 + counts["info"] * 0.05) / total_books
        health_score = max(0.0, round(100 - penalty * 100, 1))
    else:
        health_score = 100.0

    return {
        "health_score": health_score,
        "total_books": total_books,
        "unresolved_total": total_unresolved,
        "critical_count": counts["critical"],
        "warning_count": counts["warning"],
        "info_count": counts["info"],
        "resolved_count": resolved_count,
        "last_audit_at": get_setting("integrity_audit_last_run", ""),
        "audit_running": _audit_running,
    }


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


def bulk_repair_by_level(level, operator):
    """指定した重要度（通常はcritical）の未解決findingsを一括修復する。

    2026-07-06〜07: ランダムサンプル検証（計45件超）でcriticalカテゴリの
    精度がほぼ100%と確認できたため、管理者の明示的な一括承認操作を前提に
    まとめて修復できるようにした。1件ずつの手動承認（repair_finding）と
    異なり、対象件数が多い場合の運用負荷を下げる目的。
    critical判定の対象フィールドは常にtitle・author・publisherの3つとする
    （critical = title mismatch かつ author mismatch を意味するため）。
    """
    con = get_con()
    try:
        rows = fetchall(
            con,
            "SELECT * FROM integrity_findings WHERE resolved=%s" if USE_PG else "SELECT * FROM integrity_findings WHERE resolved=0",
            (False,) if USE_PG else ()
        )
        con.close()
    except Exception as e:
        logger.error(f"一括修復: 対象取得エラー {e}", exc_info=True)
        return {"error": str(e)}, 500

    targets = [r for r in rows if severity_info(r.get("mismatch_fields", ""))["level"] == level]
    repaired = 0
    errors = []
    for r in targets:
        fields = [f for f in ("title", "author", "publisher")]
        result, code = repair_finding(r["isbn"], fields, operator)
        if code == 200:
            repaired += 1
        else:
            errors.append({"isbn": r["isbn"], "error": result.get("error")})

    logger.info(f"一括修復({level}): {repaired}/{len(targets)}件完了、エラー{len(errors)}件")
    return {"ok": True, "target_count": len(targets), "repaired": repaired, "errors": errors}, 200

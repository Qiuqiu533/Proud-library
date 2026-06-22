from __future__ import annotations
import logging
import json
from typing import Any

logger = logging.getLogger(__name__)

from database import get_con, execute, fetchall, fetchone, USE_PG
from services.utils import _ndc_to_genre, _keyword_genre


def _normalize_pubdate(s: str | None) -> str:
    """OpenBDのpubdate(YYYYMM or YYYYMMDD)をYYYY-MMに正規化してソートを統一する"""
    if not s:
        return ""
    s = s.strip().replace("-", "")
    if len(s) >= 6 and s[:6].isdigit():
        return s[:4] + "-" + s[4:6]
    return ""


def _sync_awards_from_master(con: Any, isbn: str, title: str, author: str) -> None:
    """awards_masterを参照して genre_books.awards を自動設定する"""
    if not USE_PG:
        return
    try:
        from difflib import SequenceMatcher
        import unicodedata
        def _norm(s): return unicodedata.normalize("NFKC", s or "").strip()
        def _sim(a, b): return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

        cur = con.cursor()
        cur.execute("SELECT award, year, rank, type, title, author FROM awards_master")
        masters = cur.fetchall()

        matched = []
        for m in masters:
            mt, ma = _norm(m[4]), _norm(m[5] or "")
            nt, na = _norm(title), _norm(author)
            ts = _sim(mt, nt)
            title_ok = ts >= 0.82 or (len(mt) >= 6 and mt in nt) or (len(mt) >= 6 and nt in mt)
            if title_ok:
                as_ = _sim(ma, na) if ma else 0.5
                if ts * 0.7 + as_ * 0.3 >= 0.65:
                    entry = {"award": m[0], "year": m[1], "type": m[3]}
                    if m[2]: entry["rank"] = m[2]
                    already = any(a["award"] == m[0] and a["year"] == m[1] for a in matched)
                    if not already:
                        matched.append(entry)

        if matched:
            cur.execute(
                "UPDATE genre_books SET awards=%s::jsonb WHERE isbn=%s",
                (json.dumps(matched, ensure_ascii=False), isbn)
            )
    except Exception as e:
        logger.error(f"awards sync error: %s", e)


def _insert_genre_books(con: Any, genre_map: dict[str, list[dict[str, Any]]]) -> None:
    """ジャンルマップをDBに一括挿入（descriptionを保持しつつ更新）"""
    for genre, books in genre_map.items():
        for b in books:
            isbn = b.get("isbn", "")
            if not isbn:
                continue
            if USE_PG:
                execute(con,
                    "INSERT INTO genre_books (isbn,genre,title,author,publisher,format) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(isbn) DO UPDATE SET genre=EXCLUDED.genre,"
                    "title=EXCLUDED.title,author=EXCLUDED.author,publisher=EXCLUDED.publisher,format=EXCLUDED.format",
                    (isbn, genre, b.get("title",""), b.get("author",""), b.get("publisher",""), b.get("format","")))
                _sync_awards_from_master(con, isbn, b.get("title",""), b.get("author",""))
            else:
                execute(con,
                    "INSERT INTO genre_books (isbn,genre,title,author,publisher,format) VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(isbn) DO UPDATE SET genre=excluded.genre,title=excluded.title,"
                    "author=excluded.author,publisher=excluded.publisher,format=excluded.format",
                    (isbn, genre, b.get("title",""), b.get("author",""), b.get("publisher",""), b.get("format","")))
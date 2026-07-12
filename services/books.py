import json
import re as _re
import threading
import logging
import uuid

logger = logging.getLogger(__name__)
import requests

from config import (
    LIBRARYLIFE_BASE, LIBRARY_CODE, OPENBD_API, NDL_THUMB, NDL_SRU_API,
    _KANA_ROWS, KEYWORD_GENRE, NDC_TO_GENRE,
)
from database import get_con, db_session, execute, fetchone, fetchall, USE_PG
from services.utils import _keyword_genre, _ndc_to_genre

import re as _re_inertia

_INERTIA_VERSION = "b51c5455938e97b0347aeb6ea4713dc5"
_INERTIA_SESSION = requests.Session()


def _refresh_inertia_version(resp_409=None):
    """librarylife.netからInertiaバージョンを取得して更新する。"""
    global _INERTIA_VERSION
    if resp_409 is not None:
        try:
            body = resp_409.json()
            v = body.get("version") or body.get("props", {}).get("version")
            if v and len(v) == 32:
                _INERTIA_VERSION = v
                return
        except Exception:
            pass
    try:
        resp = _INERTIA_SESSION.get(f"{LIBRARYLIFE_BASE}/", timeout=10)
        m = (_re_inertia.search(r'version&quot;:&quot;([a-f0-9]{32})', resp.text)
             or _re_inertia.search(r'"version":"([a-f0-9]{32})"', resp.text))
        if m:
            _INERTIA_VERSION = m.group(1)
    except Exception as e:
        logger.error(f"_refresh_inertia_version error: %s", e)


# 起動時にバージョンを取得
threading.Thread(target=_refresh_inertia_version, daemon=True).start()


def _inertia_headers(partial_data=None, partial_component=None):
    h = {
        "Accept": "application/json",
        "X-Inertia": "true",
        "X-Inertia-Version": _INERTIA_VERSION,
    }
    if partial_data:
        h["X-Inertia-Partial-Data"] = partial_data
        h["X-Inertia-Partial-Component"] = partial_component or ""
    return h


def get_cover_url(isbn13, isbn10=""):
    # NDLを第1候補（安定・ホットリンク制限なし）。Amazon URLはフロントのonerrorで補完。
    return NDL_THUMB.format(isbn=isbn13)


def isbn13_to_isbn10(isbn13):
    if not isbn13 or not isbn13.startswith("978") or len(isbn13) < 13:
        return ""
    digits = isbn13[3:12]
    total = sum((10 - i) * int(d) for i, d in enumerate(digits))
    check = (11 - (total % 11)) % 11
    return digits + ("X" if check == 10 else str(check))


def fetch_books(keyword="", page=1):
    url = f"{LIBRARYLIFE_BASE}/booksearch"
    params = {"location": LIBRARY_CODE, "keyword": keyword, "page": page}
    try:
        resp = _INERTIA_SESSION.get(url, params=params, timeout=10,
                                    headers=_inertia_headers("books", "book-search/index"))
        if resp.status_code == 409:
            _refresh_inertia_version(resp)
            resp = _INERTIA_SESSION.get(url, params=params, timeout=10,
                                        headers=_inertia_headers("books", "book-search/index"))
        data = resp.json()
        books_data = data.get("props", {}).get("books", {})
        raw = books_data.get("data", [])
        total = books_data.get("total", len(raw))
        books = []
        for b in raw:
            isbn = b.get("isbn13", "")
            isbn10 = b.get("isbn10", "")
            books.append({
                "isbn": isbn, "isbn10": isbn10,
                "title": b.get("title", ""),
                "author": b.get("author_name", ""),
                "publisher": b.get("publisher_name", ""),
                "format": b.get("binding_kind", ""),
                "cover": b.get("cover_image") or get_cover_url(isbn, isbn10),
            })
        return {"books": books, "total": total, "page": page}
    except Exception as e:
        logger.error(f"fetch_books error: %s", e)
        return {"books": [], "total": 0, "page": page}


def fetch_book_detail(isbn, hint_title=""):
    url = f"{LIBRARYLIFE_BASE}/booksearch/detail/{isbn}"
    result = {"isbn": isbn}
    availability = []
    try:
        resp = _INERTIA_SESSION.get(url, timeout=10, headers=_inertia_headers())
        if resp.status_code == 409:
            _refresh_inertia_version(resp)
            resp = _INERTIA_SESSION.get(url, timeout=10, headers=_inertia_headers())
        data = resp.json()
        book = data.get("props", {}).get("book", {})
        result["title"] = book.get("title", "")
        result["author"] = book.get("author", "")
        result["publisher"] = book.get("publisher", "")
        result["format"] = book.get("binding", "")
        result["pubdate"] = book.get("publication_date", "")
        result["isbn13"] = book.get("isbn13", isbn)
        result["isbn10"] = book.get("isbn10", "")
        result["pages"] = str(book.get("pages", ""))
        availability = []
        for s in book.get("stocks", []):
            location = s.get("location", "")
            state = s.get("state", "")
            if location and state:
                availability.append({"library": location, "status": state})
        result["availability"] = availability
    except Exception as e:
        logger.error(f"fetch_book_detail error: %s", e)
        result["availability"] = []
    # キャッシュ保存
    if availability:
        statuses = [a["status"] for a in availability]
        if any(s in ("利用可能", "在架", "開架") for s in statuses):
            avail_status = "available"
        elif any("貸出中" in s for s in statuses):
            avail_status = "loaned"
        else:
            avail_status = "unknown"
        def _save_cache(isbn_, status_, title_, author_):
            try:
                with db_session() as c:
                    if USE_PG:
                        execute(c, """INSERT INTO availability_cache (isbn, status, title, author, updated_at)
                            VALUES (%s,%s,%s,%s,NOW()) ON CONFLICT (isbn) DO UPDATE SET
                            status=EXCLUDED.status, title=EXCLUDED.title, author=EXCLUDED.author, updated_at=NOW()
                        """, (isbn_, status_, title_, author_))
                    else:
                        execute(c, """INSERT OR REPLACE INTO availability_cache (isbn, status, title, author, updated_at)
                            VALUES (?,?,?,?,datetime('now','localtime'))""", (isbn_, status_, title_, author_))
                    c.commit()
            except Exception:
                pass
        threading.Thread(target=_save_cache, args=(isbn, avail_status, result.get("title",""), result.get("author","")), daemon=True).start()
    isbn10 = result.get("isbn10", "")
    isbn13 = result.get("isbn13", isbn)
    result["cover"] = get_cover_url(isbn13, isbn10)
    # DBの書評を取得
    try:
        dc = get_con()
        ph = "%s" if USE_PG else "?"
        lib_title = result.get("title", "").strip() or hint_title
        lib_author = result.get("author", "").strip()

        def _title_core(t):
            return _re.sub(r'[\s\(（【〈\[<＜].*', '', t).strip()

        def _title_match(t1, t2):
            if not t1 or not t2:
                return True
            c1, c2 = _title_core(t1), _title_core(t2)
            return c1 == c2 or c1 in t2 or c2 in t1 or c1 in c2 or c2 in c1

        try:
            cached = fetchone(dc, f"SELECT title, author, description, manual_review, manual_review_date, ai_review_date, ai_review_score, ai_review_confidence, ai_model, helpful_count, ai_summary, ai_tags FROM genre_books WHERE isbn={ph}", (isbn,))
        except Exception:
            # 古いDBでカラムが足りない場合は最小セットでフォールバック
            try:
                cached = fetchone(dc, f"SELECT title, author, description, helpful_count, ai_summary, ai_tags FROM genre_books WHERE isbn={ph}", (isbn,))
            except Exception:
                cached = None

        if cached and cached.get("description") and lib_title:
            if not _title_match(lib_title, cached.get("title", "")):
                cached = None

        if (not cached or not cached.get("description")) and lib_title:
            _title_cols = "title, author, description, manual_review, manual_review_date, ai_review_date, ai_review_score, ai_review_confidence, ai_model, ai_summary, ai_tags"
            try:
                cached = fetchone(dc, f"SELECT {_title_cols} FROM genre_books WHERE title={ph}", (lib_title,))
            except Exception:
                cached = fetchone(dc, f"SELECT title, author, description, ai_summary, ai_tags FROM genre_books WHERE title={ph}", (lib_title,))
            if not cached or not cached.get("description"):
                title_prefix = _title_core(lib_title)
                if len(title_prefix) >= 4:
                    try:
                        cached = fetchone(dc, f"SELECT {_title_cols} FROM genre_books WHERE title LIKE {ph}", (title_prefix + "%",))
                    except Exception:
                        cached = fetchone(dc, f"SELECT title, author, description, ai_summary, ai_tags FROM genre_books WHERE title LIKE {ph}", (title_prefix + "%",))

        dc.close()
        if cached and cached.get("description"):
            result["description"] = cached["description"]
        if cached and cached.get("manual_review") and result.get("description"):
            result["manual_review"] = True
            d = cached.get("manual_review_date")
            if d:
                result["manual_review_date"] = str(d)
        elif cached and not cached.get("manual_review") and result.get("description"):
            ai_d = cached.get("ai_review_date")
            ai_s = cached.get("ai_review_score")
            ai_c = cached.get("ai_review_confidence")
            ai_m = cached.get("ai_model")
            if ai_d:
                result["ai_review_date"] = str(ai_d)
            if ai_s:
                result["ai_review_score"] = int(ai_s)
            if ai_c:
                result["ai_review_confidence"] = int(ai_c)
            if ai_m:
                result["ai_model"] = ai_m
        if cached and result.get("description"):
            hc = cached.get("helpful_count")
            if hc:
                result["helpful_count"] = int(hc)
        if cached:
            ai_sum = cached.get("ai_summary")
            if ai_sum:
                result["ai_summary"] = ai_sum
            ai_tags_raw = cached.get("ai_tags")
            if ai_tags_raw:
                try:
                    import json as _json
                    result["ai_tags"] = _json.loads(ai_tags_raw) if isinstance(ai_tags_raw, str) else ai_tags_raw
                except Exception:
                    pass
    except Exception:
        pass
    if isbn13 and isbn13.startswith("978"):
        try:
            ob = requests.get(OPENBD_API, params={"isbn": isbn13}, timeout=5).json()
            if ob and ob[0]:
                summary = ob[0].get("summary", {})
                if not result.get("author") and summary.get("author"):
                    result["author"] = summary["author"]
                if not result.get("publisher") and summary.get("publisher"):
                    result["publisher"] = summary["publisher"]
                if summary.get("cover"):
                    result["cover"] = summary["cover"]
                if not result.get("description"):
                    for t in ob[0].get("onix", {}).get("CollateralDetail", {}).get("TextContent", []):
                        if t.get("TextType") in ("02", "03", "04"):
                            result["description"] = t.get("Text", "")
                            break
        except Exception:
            pass
    # Google Books APIで説明文を補完
    if not result.get("description") and isbn13:
        try:
            gb = requests.get(
                "https://www.googleapis.com/books/v1/volumes",
                params={"q": f"isbn:{isbn13}", "maxResults": 1},
                timeout=5
            ).json()
            items = gb.get("items", [])
            if items:
                vi = items[0].get("volumeInfo", {})
                desc = vi.get("description", "")
                if desc:
                    result["description"] = desc[:600]
                    def _save_desc(isbn_, desc_, title_, author_, publisher_):
                        try:
                            with db_session() as dc:
                                ph = "%s" if USE_PG else "?"
                                existing = fetchone(dc, f"SELECT description FROM genre_books WHERE isbn={ph}", (isbn_,))
                                if existing and existing.get("description"):
                                    return
                                if USE_PG:
                                    execute(dc, """INSERT INTO genre_books (isbn, title, author, publisher, genre, format, description)
                                        VALUES (%s,%s,%s,%s,'その他','その他',%s)
                                        ON CONFLICT (isbn) DO UPDATE SET description=EXCLUDED.description""",
                                        (isbn_, title_, author_, publisher_, desc_))
                                else:
                                    execute(dc, "UPDATE genre_books SET description=? WHERE isbn=?", (desc_, isbn_))
                                dc.commit()
                        except Exception:
                            pass
                    threading.Thread(target=_save_desc, args=(
                        isbn, desc[:600],
                        result.get("title",""), result.get("author",""), result.get("publisher","")
                    ), daemon=True).start()
                if not result.get("publisher") and vi.get("publisher"):
                    result["publisher"] = vi["publisher"]
                if not result.get("pubdate") and vi.get("publishedDate"):
                    result["pubdate"] = vi["publishedDate"].replace("-", "")
                if not result.get("pages") and vi.get("pageCount"):
                    result["pages"] = str(vi["pageCount"])
        except Exception:
            pass
    return result


def _parse_reviews(raw) -> list:
    """reviews カラムを [{id, room, text}] 形式に正規化する。旧形式（文字列配列）も変換。"""
    items = json.loads(raw or "[]")
    result = []
    for item in items:
        if isinstance(item, str):
            result.append({"id": str(uuid.uuid4()), "room": None, "text": item})
        elif isinstance(item, dict):
            result.append(item)
    return result


def _parse_user_votes(raw) -> dict:
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def get_rating(isbn, viewer_room: str | None = None):
    con = get_con()
    row = fetchone(con, "SELECT score, votes, reviews, user_votes FROM ratings WHERE isbn=?", (isbn,))
    con.close()
    if row:
        reviews = _parse_reviews(row["reviews"])
        user_votes = _parse_user_votes(row.get("user_votes") or "{}")
        my_score = user_votes.get(viewer_room) if viewer_room else None
        return {
            "score": row["score"], "votes": row["votes"],
            "reviews": reviews,
            "my_score": my_score,
        }
    return {"score": 0, "votes": 0, "reviews": [], "my_score": None}


def get_ratings_bulk(isbns):
    if not isbns:
        return {}
    con = get_con()
    placeholders = ",".join(["?" for _ in isbns])
    rows = fetchall(con, f"SELECT isbn, score, votes, reviews FROM ratings WHERE isbn IN ({placeholders})", tuple(isbns))
    con.close()
    result = {}
    for row in rows:
        result[row["isbn"]] = {"score": row["score"], "votes": row["votes"], "reviews": _parse_reviews(row["reviews"])}
    return result


def save_rating(isbn: str, score: int, review: str = "", room: str | None = None) -> dict:
    """評価を保存。room が指定された場合は同一ユーザーの重複投票を防ぐ（更新として扱う）。"""
    con = get_con()
    existing = fetchone(con, "SELECT score, votes, reviews, user_votes FROM ratings WHERE isbn=?", (isbn,))
    if existing:
        user_votes = _parse_user_votes(existing.get("user_votes") or "{}")
        reviews = _parse_reviews(existing["reviews"])
        if room and room in user_votes:
            # 同一ユーザーの再投票 → スコアを更新、コメントは追加しない
            old_score = user_votes[room]
            user_votes[room] = score
            total = sum(user_votes.values()) if user_votes else score
            new_votes = len(user_votes)
            new_score = round(total / new_votes, 1)
        else:
            new_votes = existing["votes"] + 1
            new_score = round((existing["score"] * existing["votes"] + score) / new_votes, 1)
            if room:
                user_votes[room] = score
            if review:
                reviews.append({"id": str(uuid.uuid4()), "room": room, "text": review})
        execute(con, "UPDATE ratings SET score=?, votes=?, reviews=?, user_votes=? WHERE isbn=?",
                (new_score, new_votes,
                 json.dumps(reviews, ensure_ascii=False),
                 json.dumps(user_votes, ensure_ascii=False),
                 isbn))
    else:
        user_votes = {room: score} if room else {}
        reviews = [{"id": str(uuid.uuid4()), "room": room, "text": review}] if review else []
        execute(con, "INSERT INTO ratings (isbn, score, votes, reviews, user_votes) VALUES (?,?,?,?,?)",
                (isbn, float(score), 1,
                 json.dumps(reviews, ensure_ascii=False),
                 json.dumps(user_votes, ensure_ascii=False)))
    con.commit()
    con.close()


def delete_review(isbn: str, review_id: str, room: str) -> bool:
    """自分のコメントを削除する。room が一致する場合のみ削除可。"""
    con = get_con()
    existing = fetchone(con, "SELECT reviews FROM ratings WHERE isbn=?", (isbn,))
    if not existing:
        con.close()
        return False
    reviews = _parse_reviews(existing["reviews"])
    new_reviews = [r for r in reviews if not (r.get("id") == review_id and r.get("room") == room)]
    if len(new_reviews) == len(reviews):
        con.close()
        return False
    execute(con, "UPDATE ratings SET reviews=? WHERE isbn=?",
            (json.dumps(new_reviews, ensure_ascii=False), isbn))
    con.commit()
    con.close()
    return True


_recent_isbns_cache = {"isbns": [], "date": None}


def _upsert_setting(con, key, value):
    if USE_PG:
        execute(con, "INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, value))
    else:
        execute(con, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))


def _build_recent_isbns():
    """OpenBDを叩いて直近5年の本リストを構築しDBにキャッシュ"""
    import datetime
    today = datetime.date.today()
    try:
        with db_session() as con:
            rows = fetchall(con, "SELECT isbn, title, author, publisher FROM genre_books")
        if not rows:
            return []
        isbns = [r["isbn"] for r in rows]
        info_map = {r["isbn"]: r for r in rows}
        cutoff_year = str(today.year - 5)
        recent = []
        for i in range(0, len(isbns), 1000):
            batch = isbns[i:i+1000]
            resp = requests.get(OPENBD_API, params={"isbn": ",".join(batch)}, timeout=20)
            for item in resp.json():
                if not item:
                    continue
                try:
                    pubdate = item["summary"].get("pubdate", "") or ""
                    isbn = item["summary"].get("isbn", "")
                    if pubdate >= cutoff_year and isbn in info_map:
                        cover = item["summary"].get("cover", "")
                        rec = dict(info_map[isbn])
                        rec["cover"] = cover or get_cover_url(isbn, isbn13_to_isbn10(isbn))
                        recent.append(rec)
                except Exception:
                    pass
        with db_session() as con2:
            _upsert_setting(con2, "recent_books_cache", json.dumps(recent, ensure_ascii=False))
            _upsert_setting(con2, "recent_books_cache_date", str(today))
            con2.commit()
        _recent_isbns_cache["isbns"] = recent
        _recent_isbns_cache["date"] = today
        return recent
    except Exception as e:
        logger.error(f"recent_isbns build error: %s", e)
        return []


def get_recent_isbns():
    import datetime
    today = datetime.date.today()
    cache = _recent_isbns_cache
    if cache["date"] == today and cache["isbns"]:
        return cache["isbns"]
    try:
        with db_session() as con:
            date_row = fetchone(con, "SELECT value FROM settings WHERE key='recent_books_cache_date'")
            if date_row and date_row["value"] == str(today):
                data_row = fetchone(con, "SELECT value FROM settings WHERE key='recent_books_cache'")
                if data_row:
                    isbns = json.loads(data_row["value"])
                    cache["isbns"] = isbns
                    cache["date"] = today
                    return isbns
    except Exception:
        pass
    threading.Thread(target=_build_recent_isbns, daemon=True).start()
    return cache.get("isbns", [])


def _save_genre_update_time():
    import datetime
    now = datetime.datetime.now().isoformat()
    try:
        con = get_con()
        if USE_PG:
            execute(con,
                "INSERT INTO settings (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                ("genre_last_update", now))
        else:
            execute(con,
                "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                ("genre_last_update", now))
        con.commit(); con.close()
    except Exception as e:
        logger.error(f"_save_genre_update_time error: %s", e)


def _classify_genre(ndc, title="", description=""):
    """NDCコード＋キーワードでジャンルを自動判定"""
    from config import NDC_TO_GENRE, KEYWORD_GENRE
    combined = (title or "") + " " + (description or "")

    # 1. NDCコードで判定（最優先・長いコードから順にマッチ）
    n = str(ndc or "").strip()
    if n:
        for length in (4, 3, 2):
            prefix = n[:length]
            if prefix in NDC_TO_GENRE:
                return NDC_TO_GENRE[prefix]
        # NDCの大分類フォールバック
        if n.startswith("726") or n.startswith("72"): return "絵本・児童書"
        if n.startswith("91"):  return "文芸小説"
        if n[:1] == "9":        return "翻訳小説"
        if n[:1] in ("1","2","3","4","5","6","0"): return "実用・ハウツー"

    # 2. タイトル・説明のキーワードで判定
    for words, genre in KEYWORD_GENRE:
        if any(w in combined for w in words):
            return genre

    # 3. どれにも当てはまらない場合は「その他」
    return "その他"


def audit_genre_ndc_mismatches(limit: int = 200) -> list[dict]:
    """genre_books.ndcが保存されている本のうち、現在のNDC_TO_GENREマッピングで
    再計算した場合に現在のgenreと異なる結果になるものを検出する。

    2026-07-12: 「風姿花伝」（NDC773・能楽）がNDC_TO_GENREに未対応だったため
    「ミステリ・推理」に誤分類されていた事故を受けて追加。自動修復はせず、
    検出のみ行い管理者が確認できるようにする（ISBN整合性監査と同じ方針:
    自動上書きすると逆に壊すリスクがあるため）。
    """
    con = get_con()
    try:
        rows = fetchall(
            con,
            "SELECT isbn, title, genre, ndc FROM genre_books "
            "WHERE ndc IS NOT NULL AND ndc != '' ORDER BY isbn LIMIT %s" if USE_PG else
            "SELECT isbn, title, genre, ndc FROM genre_books "
            "WHERE ndc IS NOT NULL AND ndc != '' ORDER BY isbn LIMIT ?",
            (limit,),
        )
    finally:
        con.close()

    mismatches = []
    for r in rows:
        current_genre = r.get("genre") or "その他"
        suggested_genre = _classify_genre(r.get("ndc", ""), r.get("title", ""), "")
        if suggested_genre != current_genre:
            mismatches.append({
                "isbn": r["isbn"],
                "title": r.get("title", ""),
                "ndc": r.get("ndc", ""),
                "current_genre": current_genre,
                "suggested_genre": suggested_genre,
            })
    return mismatches


def _ndc_has_known_mapping(ndc: str) -> bool:
    """NDC_TO_GENREに明示的な対応がある（キーワード判定等の推測に頼らない）かどうか。"""
    from config import NDC_TO_GENRE
    n = str(ndc or "").strip()
    if not n:
        return False
    for length in (4, 3, 2):
        if n[:length] in NDC_TO_GENRE:
            return True
    return False


def data_quality_summary() -> dict:
    """genre×NDCのデータ品質サマリーを返す。

    2026-07-12: 「風姿花伝」「歴史探偵忘れ残りの記」の2件が、いずれもndc列が
    空だったためaudit_genre_ndc_mismatches()の対象外（監査の死角）になって
    いたことが実データで判明。「NDCが無い本は監査できない」という監査の
    限界そのものを可視化し、早期発見できるようにする。
    """
    con = get_con()
    try:
        total = fetchone(con, "SELECT COUNT(*) as cnt FROM genre_books")["cnt"]
        ndc_missing = fetchone(
            con,
            "SELECT COUNT(*) as cnt FROM genre_books WHERE ndc IS NULL OR ndc = ''"
        )["cnt"]
        ndc_rows = fetchall(con, "SELECT ndc FROM genre_books WHERE ndc IS NOT NULL AND ndc != ''")
        isbn_rows = fetchall(con, "SELECT isbn FROM genre_books")
    finally:
        con.close()

    ndc_unmapped = sum(1 for r in ndc_rows if not _ndc_has_known_mapping(r.get("ndc", "")))
    invalid_isbn = sum(
        1 for r in isbn_rows
        if not (r.get("isbn") and len(r["isbn"]) == 13 and r["isbn"].startswith(("978", "979")))
    )

    return {
        "total_books": total,
        "ndc_missing_count": ndc_missing,
        "ndc_present_count": total - ndc_missing,
        "ndc_unmapped_count": ndc_unmapped,
        "invalid_isbn_count": invalid_isbn,
        "note": "ndc_missing_countの本はgenre×NDC監査（audit_genre_ndc_mismatches）の対象外です。"
                "invalid_isbn_countは978/979始まりの13桁ISBNでない本（librarylife.netの仮ISBN等）で、NDC補完の対象外です。",
    }


def list_books_missing_ndc(limit: int = 100) -> list[dict]:
    """ndcが未取得の本の一覧を返す（NDC欠落の可視化用）。"""
    con = get_con()
    try:
        rows = fetchall(
            con,
            "SELECT isbn, title, genre FROM genre_books WHERE ndc IS NULL OR ndc = '' "
            "ORDER BY isbn LIMIT %s" if USE_PG else
            "SELECT isbn, title, genre FROM genre_books WHERE ndc IS NULL OR ndc = '' "
            "ORDER BY isbn LIMIT ?",
            (limit,),
        )
        return rows
    finally:
        con.close()


_ndc_backfill_running = False
_ndc_backfill_last_result = None


def is_ndc_backfill_running() -> bool:
    return _ndc_backfill_running


def get_ndc_backfill_last_result():
    return _ndc_backfill_last_result


def run_ndc_backfill(operator: str, limit: int = 100000):
    """NDC未取得の本にOpenBDからNDCを取得し、genreを再分類する（バックグラウンド実行）。

    2026-07-12: 5,156冊中2,369件（46%）がNDC未取得で、genre×NDC監査
    （audit_genre_ndc_mismatches）の対象外になっていることが判明。「風姿花伝」
    「歴史探偵忘れ残りの記」の2件がこのパターンで誤分類を見逃していたため、
    NDCを補完して監査の対象範囲を広げる。

    結果は理由別に分類して記録する（取得成功／OpenBDにデータなし／
    OpenBDにNDCなし／APIエラー）。これにより「2,369件のうち実際に補完可能
    なのは何件か」を後から判断できるようにする。

    genreの更新は_auto_classify_new_books（新規本の自動分類）と同じく
    確認なしで直接適用する（NDCという客観的な事実データの補完であり、
    既存の書誌情報を上書きする整合性監査とは性質が異なるため）。
    """
    import time
    global _ndc_backfill_running, _ndc_backfill_last_result

    if _ndc_backfill_running:
        return {"error": "既に実行中です"}, 409

    def _run():
        global _ndc_backfill_running, _ndc_backfill_last_result
        _ndc_backfill_running = True
        try:
            con = get_con()
            try:
                # 2026-07-12: LIKE '978%' のようにSQL文中へワイルドカードを直接
                # 埋め込むと、PostgreSQL接続時にpsycopg2の%sプレースホルダ解釈と
                # 衝突し本番でのみ例外（tuple index out of range）が発生した。
                # ワイルドカードをパラメータとして渡すことで回避する。
                ph = "%s" if USE_PG else "?"
                rows = fetchall(
                    con,
                    f"SELECT isbn, title, genre FROM genre_books WHERE (ndc IS NULL OR ndc = '') "
                    f"AND (isbn LIKE {ph} OR isbn LIKE {ph}) "
                    f"ORDER BY isbn LIMIT {ph}",
                    ("978%", "979%", limit),
                )
            finally:
                con.close()

            # 有効なISBN-13（978/979始まり）のみを対象にする。librarylife.netの
            # 仮ISBN・不正なISBNはOpenBDに存在しえないため、NDC補完の対象外とする
            # （2026-07-12: limit=200の試験実行で全件がno_data_in_openbdになり、
            # 昇順ソートの先頭に仮ISBNが集中していたことが判明したため対応）。
            targets = [r for r in rows if r["isbn"] and len(r["isbn"]) == 13]
            counts = {
                "success": 0, "genre_changed": 0, "no_data_in_openbd": 0,
                "no_ndc_in_openbd": 0, "api_error": 0,
            }
            batch_size = 500

            for i in range(0, len(targets), batch_size):
                batch = targets[i:i + batch_size]
                isbns = [b["isbn"] for b in batch]
                book_map = {b["isbn"]: b for b in batch}
                ndc_map = {}
                found_isbns = set()
                try:
                    resp = requests.get(OPENBD_API, params={"isbn": ",".join(isbns)}, timeout=60)
                    items = resp.json()
                    if not isinstance(items, list):
                        logger.error(f"NDC補完: OpenBDレスポンスがリストでない: {type(items)} {str(items)[:300]}")
                        items = []
                    # OpenBDが要求件数より少ない/多い配列を返すケースに備え、
                    # zipではなくindexで安全に対応させる（2026-07-12: 本番で
                    # "tuple index out of range" が発生した原因調査を兼ねる）。
                    for idx, isbn in enumerate(isbns):
                        item = items[idx] if idx < len(items) else None
                        if not item:
                            continue
                        try:
                            found_isbns.add(isbn)
                            subjects = item.get("onix", {}).get("DescriptiveDetail", {}).get("Subject", [])
                            if isinstance(subjects, dict):
                                subjects = [subjects]
                            if not isinstance(subjects, list):
                                subjects = []
                            ndc = ""
                            for s in subjects:
                                if isinstance(s, dict) and s.get("SubjectSchemeIdentifier") == "78":
                                    ndc = s.get("SubjectCode", "")
                                    break
                            if ndc:
                                ndc_map[isbn] = ndc
                        except Exception as e:
                            logger.error(f"NDC補完: ISBN {isbn} のパースエラー: {e} / item={str(item)[:300]}",
                                         exc_info=True)
                except Exception as e:
                    logger.error(f"NDC補完: OpenBDバッチエラー: {e}", exc_info=True)
                    for isbn in isbns:
                        counts["api_error"] += 1
                    time.sleep(1)
                    continue

                with db_session() as bcon:
                    for isbn in isbns:
                        if isbn not in found_isbns:
                            counts["no_data_in_openbd"] += 1
                            continue
                        ndc = ndc_map.get(isbn, "")
                        if not ndc:
                            counts["no_ndc_in_openbd"] += 1
                            continue
                        try:
                            book = book_map[isbn]
                            old_genre = book.get("genre") or "その他"
                            new_genre = _classify_genre(ndc, book.get("title", ""), "")
                            ph = "%s" if USE_PG else "?"
                            execute(bcon, f"UPDATE genre_books SET ndc={ph}, genre={ph} WHERE isbn={ph}",
                                    (ndc, new_genre, isbn))
                            counts["success"] += 1
                            if new_genre != old_genre:
                                counts["genre_changed"] += 1
                        except Exception as e:
                            logger.error(f"NDC補完: ISBN {isbn} のDB更新エラー: {e}", exc_info=True)
                            counts["api_error"] += 1
                    bcon.commit()
                time.sleep(0.5)

            _ndc_backfill_last_result = {"target_count": len(targets), **counts, "operator": operator}
            logger.info(f"NDC補完: {counts}")
        except Exception as e:
            logger.error(f"NDC補完エラー: {e}", exc_info=True)
            _ndc_backfill_last_result = {"error": str(e)}
        finally:
            _ndc_backfill_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}, 200


def fetch_ndc_from_ndl(isbn: str) -> str:
    """NDL（国立国会図書館サーチ）SRU APIからNDCコードを取得する。

    OpenBDにはNDCが登録されていない本でも、NDLには登録されている場合がある
    （2026-07-12: 全件実行の結果、残り約2,308件のうち約1,789件がこのケースと
    判明）。SRUのレスポンスはXMLだがJSON解析するほどの構造化は不要なため、
    scripts/fetch_ndc_ndl.py と同じく正規表現でNDC（ndc9/形式）を抽出する。
    """
    try:
        resp = requests.get(NDL_SRU_API, params={
            "operation": "searchRetrieve",
            "version": "1.2",
            "recordSchema": "dcndl",
            "maximumRecords": "1",
            "query": f'isbn="{isbn}"',
        }, timeout=15)
        decoded = resp.text
        m = _re.search(r"ndc9/([0-9.]+)", decoded)
        return m.group(1) if m else ""
    except Exception:
        return ""


_ndl_backfill_running = False
_ndl_backfill_last_result = None


def is_ndl_backfill_running() -> bool:
    return _ndl_backfill_running


def get_ndl_backfill_last_result():
    return _ndl_backfill_last_result


def run_ndl_backfill(operator: str, limit: int = 100000, workers: int = 10):
    """OpenBDで取得できなかったNDCをNDLサーチにフォールバックして補完する
    （バックグラウンド実行）。

    2026-07-12: NDC補完バッチ（OpenBD版）を全件実行した結果、残存2,308件の
    うち約1,789件はOpenBD自体にNDCが登録されておらず、OpenBDだけではこれ
    以上の改善が見込めないと判明。NDLは個別ISBNクエリのみ対応（OpenBDの
    ようなバッチ取得不可）のため、ThreadPoolExecutorで並列化する。
    """
    global _ndl_backfill_running, _ndl_backfill_last_result

    if _ndl_backfill_running:
        return {"error": "既に実行中です"}, 409

    def _run():
        global _ndl_backfill_running, _ndl_backfill_last_result
        _ndl_backfill_running = True
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            con = get_con()
            try:
                ph = "%s" if USE_PG else "?"
                rows = fetchall(
                    con,
                    f"SELECT isbn, title, genre FROM genre_books WHERE (ndc IS NULL OR ndc = '') "
                    f"AND (isbn LIKE {ph} OR isbn LIKE {ph}) "
                    f"ORDER BY isbn LIMIT {ph}",
                    ("978%", "979%", limit),
                )
            finally:
                con.close()

            targets = [r for r in rows if r["isbn"] and len(r["isbn"]) == 13]
            counts = {"success": 0, "genre_changed": 0, "no_ndc_in_ndl": 0, "api_error": 0}
            ndc_results = {}

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(fetch_ndc_from_ndl, r["isbn"]): r["isbn"] for r in targets}
                for future in as_completed(futures):
                    isbn = futures[future]
                    try:
                        ndc_results[isbn] = future.result()
                    except Exception as e:
                        logger.error(f"NDL補完: ISBN {isbn} の取得エラー: {e}", exc_info=True)
                        ndc_results[isbn] = None

            with db_session() as bcon:
                for r in targets:
                    isbn = r["isbn"]
                    ndc = ndc_results.get(isbn)
                    if ndc is None:
                        counts["api_error"] += 1
                        continue
                    if not ndc:
                        counts["no_ndc_in_ndl"] += 1
                        continue
                    try:
                        old_genre = r.get("genre") or "その他"
                        new_genre = _classify_genre(ndc, r.get("title", ""), "")
                        ph = "%s" if USE_PG else "?"
                        execute(bcon, f"UPDATE genre_books SET ndc={ph}, genre={ph} WHERE isbn={ph}",
                                (ndc, new_genre, isbn))
                        counts["success"] += 1
                        if new_genre != old_genre:
                            counts["genre_changed"] += 1
                    except Exception as e:
                        logger.error(f"NDL補完: ISBN {isbn} のDB更新エラー: {e}", exc_info=True)
                        counts["api_error"] += 1
                bcon.commit()

            _ndl_backfill_last_result = {"target_count": len(targets), **counts, "operator": operator}
            logger.info(f"NDL補完: {counts}")
        except Exception as e:
            logger.error(f"NDL補完エラー: {e}", exc_info=True)
            _ndl_backfill_last_result = {"error": str(e)}
        finally:
            _ndl_backfill_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}, 200


_genre_classify_running = False


def _auto_classify_new_books(force=False):
    """バックグラウンド：新しい本を自動検出してジャンル分類（通常は週1回、
    force=Trueの場合は管理画面からの手動実行として間隔チェックをスキップする）"""
    import time, datetime, threading
    from config import get_setting

    def _run():
        global _genre_classify_running
        if _genre_classify_running:
            logger.info("ジャンル自動更新: 既に実行中のためスキップ")
            return
        _genre_classify_running = True
        try:
            if not force:
                last = get_setting("genre_last_update", "")
                if last:
                    try:
                        last_dt = datetime.datetime.fromisoformat(last)
                        if (datetime.datetime.now() - last_dt).days < 7:
                            logger.info("ジャンル自動更新: 前回から7日未満のためスキップ")
                            return
                    except Exception:
                        pass

            logger.info("ジャンル自動更新: 開始...(force=%s)", force)
            con = get_con()
            rows = fetchall(con, "SELECT isbn FROM genre_books")
            con.close()
            known = {r["isbn"] for r in rows}

            new_books = []
            page = 1
            while True:
                try:
                    data = fetch_books("", page)
                    if not data["books"]:
                        break
                    for b in data["books"]:
                        if b["isbn"] and b["isbn"] not in known:
                            new_books.append(b)
                    if page * 50 >= data.get("total", 0):
                        break
                    page += 1
                    time.sleep(0.8)
                except Exception as e:
                    logger.info(f"ジャンル自動更新: ページ{page}取得エラー {e}")
                    break

            if not new_books:
                logger.info("ジャンル自動更新: 新しい本なし")
                _save_genre_update_time()
                return

            logger.info(f"ジャンル自動更新: {len(new_books)}冊の新しい本を分類中...")

            batch_size = 100
            classified = 0
            for i in range(0, len(new_books), batch_size):
                batch = new_books[i:i + batch_size]
                isbns = [b["isbn"] for b in batch]
                ndc_map = {}
                desc_map = {}
                try:
                    resp = requests.get(OPENBD_API, params={"isbn": ",".join(isbns)}, timeout=15)
                    for isbn, ob in zip(isbns, resp.json()):
                        if not ob:
                            continue
                        for subj in ob.get("onix", {}).get("DescriptiveDetail", {}).get("Subject", []):
                            if subj.get("SubjectSchemeIdentifier") == "78":
                                ndc_map[isbn] = subj.get("SubjectCode", "")
                                break
                        for t in ob.get("onix", {}).get("CollateralDetail", {}).get("TextContent", []):
                            if t.get("TextType") in ("02", "03", "04"):
                                desc_map[isbn] = t.get("Text", "")
                                break
                except Exception as e:
                    logger.info(f"OpenBD バッチエラー: {e}")

                with db_session() as con:
                    for b in batch:
                        isbn = b["isbn"]
                        genre = _classify_genre(
                            ndc_map.get(isbn, ""),
                            b.get("title", ""),
                            desc_map.get(isbn, "")
                        )
                        if USE_PG:
                            execute(con,
                                "INSERT INTO genre_books (isbn,genre,title,author,publisher,format) "
                                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(isbn) DO UPDATE SET "
                                "title=EXCLUDED.title, author=EXCLUDED.author, "
                                "publisher=EXCLUDED.publisher, format=EXCLUDED.format",
                                (isbn, genre, b.get("title",""), b.get("author",""),
                                 b.get("publisher",""), b.get("format","")))
                        else:
                            execute(con,
                                "INSERT OR REPLACE INTO genre_books "
                                "(isbn,genre,title,author,publisher,format) VALUES (?,?,?,?,?,?)",
                                (isbn, genre, b.get("title",""), b.get("author",""),
                                 b.get("publisher",""), b.get("format","")))
                        classified += 1
                    con.commit()
                time.sleep(0.5)

            _save_genre_update_time()
            logger.info(f"ジャンル自動更新: 完了 ({classified}冊追加)")
        except Exception as e:
            logger.info(f"ジャンル自動更新エラー: {e}")
        finally:
            _genre_classify_running = False

    threading.Thread(target=_run, daemon=True).start()


def is_genre_classify_running():
    return _genre_classify_running
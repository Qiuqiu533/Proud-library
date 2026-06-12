from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
import json
import os

# ── ジャンル別蔵書データ（Excelから事前生成）──────────────────────────────
_GENRE_MAP_PATH = os.path.join(os.path.dirname(__file__), "static", "genre_map.json")
try:
    with open(_GENRE_MAP_PATH, encoding="utf-8") as _f:
        GENRE_MAP = json.load(_f)
except Exception:
    GENRE_MAP = {}

app = Flask(__name__)

# ── DB設定 ──────────────────────────────────────────────────────────────
# DATABASE_URL が設定されていればPostgreSQL、なければSQLite（ローカル開発用）
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    # Render の postgres:// を postgresql:// に正規化
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


def get_con():
    """DB接続を返す。PostgreSQL or SQLite を自動切り替え。"""
    if USE_PG:
        con = psycopg2.connect(DATABASE_URL)
        return con
    else:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        return con


def execute(con, sql, params=()):
    """SQLiteの ? をPostgreSQLの %s に変換して実行する。"""
    if USE_PG:
        sql = sql.replace("?", "%s")
        # AUTOINCREMENT / INTEGER PRIMARY KEY → SERIAL PRIMARY KEY
    cur = con.cursor()
    cur.execute(sql, params)
    return cur


def fetchall(con, sql, params=()):
    cur = execute(con, sql, params)
    rows = cur.fetchall()
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    else:
        return [dict(r) for r in rows]


def fetchone(con, sql, params=()):
    cur = execute(con, sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    else:
        return dict(row)


# ── 定数 ────────────────────────────────────────────────────────────────
LIBRARY_CODE = "0011"
LIBRARYLIFE_BASE = "https://www2.librarylife.net"
OPENBD_API = "https://api.openbd.jp/v1/get"
NDL_THUMB = "https://ndlsearch.ndl.go.jp/thumbnail/{isbn}.jpg"

LIBRARY_INFO = {
    "name": "プラウド船橋コミュニティ図書館",
    "hours": [
        {"day": "月〜金", "time": "10:00〜18:00"},
        {"day": "土・日・祝", "time": "10:00〜17:00"},
    ],
    "closed": "第2・第4水曜日、年末年始",
    "location": "千葉県船橋市 プラウド船橋クラブハウス内",
    "note": "最新情報はlibrarlife.netをご確認ください。",
}

_ADMIN_PASSWORD_ENV    = os.environ.get("ADMIN_PASSWORD",    "proud2024")
_RESIDENT_PASSWORD_ENV = os.environ.get("RESIDENT_PASSWORD", "proudfunabashi")
_BOARD_PASSWORD_ENV    = os.environ.get("BOARD_PASSWORD",    "board2025")


def get_setting(key, default=""):
    """settings テーブルから値を取得。なければ default を返す。"""
    try:
        con = get_con()
        row = fetchone(con, "SELECT value FROM settings WHERE key=?", (key,))
        con.close()
        if row:
            return row["value"]
    except Exception:
        pass
    return default


def get_admin_password():
    return get_setting("admin_password", _ADMIN_PASSWORD_ENV)

def get_resident_password():
    return get_setting("resident_password", _RESIDENT_PASSWORD_ENV)

def get_board_password():
    return get_setting("board_password", _BOARD_PASSWORD_ENV)


# ── DB初期化 ─────────────────────────────────────────────────────────────
def init_db():
    con = get_con()
    if USE_PG:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                isbn TEXT PRIMARY KEY,
                score REAL,
                votes INTEGER,
                reviews TEXT DEFAULT '[]'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT DEFAULT 'お知らせ',
                image_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                priority TEXT DEFAULT '中',
                status TEXT DEFAULT '未対応',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS book_requests (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                room TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                body TEXT DEFAULT '',
                minutes TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_accounts (
                room TEXT PRIMARY KEY,
                pin TEXT NOT NULL,
                favorites TEXT DEFAULT '[]',
                reading_log TEXT DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        con.commit()
    else:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                isbn TEXT PRIMARY KEY,
                score REAL,
                votes INTEGER,
                reviews TEXT DEFAULT '[]'
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT DEFAULT 'お知らせ',
                image_url TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        try:
            con.execute("ALTER TABLE announcements ADD COLUMN image_url TEXT DEFAULT ''")
        except Exception:
            pass
        con.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                priority TEXT DEFAULT '中',
                status TEXT DEFAULT '未対応',
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS book_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                room TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                body TEXT DEFAULT '',
                minutes TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        for tbl in ("issues", "calendar_events"):
            try:
                con.execute(f"ALTER TABLE {tbl} ADD COLUMN sort_order INTEGER DEFAULT 0")
            except Exception:
                pass
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_accounts (
                room TEXT PRIMARY KEY,
                pin TEXT NOT NULL,
                favorites TEXT DEFAULT '[]',
                reading_log TEXT DEFAULT '{}',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()
    con.close()


def _ensure_db():
    try:
        init_db()
    except Exception as e:
        print(f"DB init error: {e}")


# ── 蔵書スクレイピング ────────────────────────────────────────────────────
def get_cover_url(isbn13, isbn10=""):
    if isbn10:
        return f"https://images-na.ssl-images-amazon.com/images/P/{isbn10}.09.LZZZZZZZ.jpg"
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
    resp = requests.get(url, params=params, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    total = 0
    page_data = soup.select_one(".page-data")
    if page_data:
        strong = page_data.find("strong")
        if strong:
            total = int(strong.text.replace(",", ""))
    books = []
    for row in soup.select("table.table tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        title_a = cols[0].find("a")
        author_a = cols[1].find("a")
        title = title_a.text.strip() if title_a else ""
        href = title_a["href"] if title_a else ""
        isbn = href.split("/")[-1] if href else ""
        author = author_a.text.strip() if author_a else ""
        isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
        books.append({
            "isbn": isbn, "isbn10": isbn10, "title": title, "author": author,
            "publisher": cols[2].text.strip(), "format": cols[3].text.strip(),
            "cover": get_cover_url(isbn, isbn10),
        })
    return {"books": books, "total": total, "page": page}


def fetch_book_detail(isbn):
    url = f"{LIBRARYLIFE_BASE}/booksearch/detail/{isbn}"
    resp = requests.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    result = {"isbn": isbn}
    result["title"] = soup.find("h1").text.strip() if soup.find("h1") else ""
    for row in soup.select("#detail-area table.table tbody tr"):
        for th, td in zip(row.find_all("th"), row.find_all("td")):
            key, val = th.text.strip(), td.text.strip()
            if key == "著者":      result["author"] = val
            elif key == "出版社":  result["publisher"] = val
            elif key == "形式":    result["format"] = val
            elif key == "出版年月日": result["pubdate"] = val
            elif key == "ISBN13":  result["isbn13"] = val
            elif key == "ISBN10":  result["isbn10"] = val
            elif key == "ページ数": result["pages"] = val
    availability = []
    for row in soup.select("table.table tbody tr"):
        tds = row.find_all("td")
        if len(tds) >= 3 and tds[1].text.strip() and tds[2].text.strip():
            availability.append({"library": tds[1].text.strip(), "status": tds[2].text.strip()})
    result["availability"] = availability
    isbn10 = result.get("isbn10", "")
    isbn13 = result.get("isbn13", isbn)
    result["cover"] = get_cover_url(isbn13, isbn10)
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
                for t in ob[0].get("onix", {}).get("CollateralDetail", {}).get("TextContent", []):
                    if t.get("TextType") in ("02", "03", "04"):
                        result["description"] = t.get("Text", "")
                        break
        except Exception:
            pass
    return result


def get_rating(isbn):
    con = get_con()
    row = fetchone(con, "SELECT score, votes, reviews FROM ratings WHERE isbn=?", (isbn,))
    con.close()
    if row:
        return {"score": row["score"], "votes": row["votes"], "reviews": json.loads(row["reviews"])}
    return {"score": 0, "votes": 0, "reviews": []}


def save_rating(isbn, score, review=""):
    con = get_con()
    existing = fetchone(con, "SELECT score, votes, reviews FROM ratings WHERE isbn=?", (isbn,))
    if existing:
        new_votes = existing["votes"] + 1
        new_score = round((existing["score"] * existing["votes"] + score) / new_votes, 1)
        reviews = json.loads(existing["reviews"])
        if review:
            reviews.append(review)
        execute(con, "UPDATE ratings SET score=?, votes=?, reviews=? WHERE isbn=?",
                (new_score, new_votes, json.dumps(reviews, ensure_ascii=False), isbn))
    else:
        reviews = [review] if review else []
        execute(con, "INSERT INTO ratings (isbn, score, votes, reviews) VALUES (?,?,?,?)",
                (isbn, float(score), 1, json.dumps(reviews, ensure_ascii=False)))
    con.commit()
    con.close()


# ── ルート ───────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth", methods=["POST"])
def api_auth():
    body = request.get_json()
    if body.get("password") == get_resident_password():
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401


@app.route("/api/board/auth", methods=["POST"])
def api_board_auth():
    body = request.get_json()
    if body.get("password") == get_board_password():
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401


# --- Issues ---
@app.route("/api/issues")
def api_issues():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,body,priority,status,sort_order,created_at FROM issues ORDER BY sort_order ASC, id DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@app.route("/api/issues", methods=["POST"])
def api_post_issue():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    row = fetchone(con, "SELECT MIN(sort_order) as m FROM issues")
    new_order = ((row["m"] or 0) - 1) if row else -1
    execute(con, "INSERT INTO issues (title,body,priority,status,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("body","").strip(),
         body.get("priority","中"), body.get("status","未対応"), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/issues/reorder", methods=["POST"])
def api_reorder_issues():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    for item in body.get("order", []):
        execute(con, "UPDATE issues SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/issues/<int:issue_id>", methods=["PATCH"])
def api_update_issue(issue_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if "title" in body:
        execute(con, "UPDATE issues SET title=?,body=?,priority=?,status=? WHERE id=?",
            (body["title"], body.get("body",""), body.get("priority","中"), body.get("status","未対応"), issue_id))
    elif "status" in body:
        execute(con, "UPDATE issues SET status=? WHERE id=?", (body["status"], issue_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/issues/<int:issue_id>", methods=["DELETE"])
def api_delete_issue(issue_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM issues WHERE id=?", (issue_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Calendar ---
@app.route("/api/calendar")
def api_calendar():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,event_date,body,minutes,sort_order,created_at FROM calendar_events ORDER BY sort_order ASC, event_date DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@app.route("/api/calendar", methods=["POST"])
def api_post_calendar():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    row = fetchone(con, "SELECT MIN(sort_order) as m FROM calendar_events")
    new_order = ((row["m"] or 0) - 1) if row else -1
    execute(con, "INSERT INTO calendar_events (title,event_date,body,minutes,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/calendar/reorder", methods=["POST"])
def api_reorder_calendar():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    for item in body.get("order", []):
        execute(con, "UPDATE calendar_events SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/calendar/<int:ev_id>", methods=["PATCH"])
def api_update_calendar(ev_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "UPDATE calendar_events SET title=?,event_date=?,body=?,minutes=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), ev_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/calendar/<int:ev_id>", methods=["DELETE"])
def api_delete_calendar(ev_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM calendar_events WHERE id=?", (ev_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Stats (pre-computed from full collection 2026-04-12) ---
FULL_STATS = {
    "total": 5470,
    "publishers": [
        ("講談社", 615), ("文藝春秋", 515), ("新潮社", 423), ("角川書店", 325),
        ("登録無し(ISBN無の為)", 290), ("集英社", 223), ("小学館", 185), ("朝日新聞社", 174),
        ("幻冬舎", 161), ("福音館書店", 142), ("光文社", 130), ("ポプラ社", 118),
        ("偕成社", 108), ("中央公論社", 91), ("双葉社", 82), ("PHP研究所", 61),
        ("早川書房", 61), ("学習研究社", 60), ("徳間書店", 58), ("岩崎書店", 57),
    ],
    "authors": [
        ("平岩 弓枝", 68), ("塩野 七生", 66), ("宮部 みゆき", 60), ("東野 圭吾", 59),
        ("韓 賢東", 49), ("藤沢 周平", 44), ("司馬 遼太郎", 43), ("佐伯 泰英", 37),
        ("村上 春樹", 33), ("赤川 次郎", 32), ("洪 在徹", 30), ("百田 尚樹", 30),
        ("池波 正太郎", 29), ("北方 謙三", 24), ("今野 敏", 23), ("あさの あつこ", 22),
        ("内田 康夫", 22), ("奥田 英朗", 21), ("廣嶋 玲子", 20), ("柚月 裕子", 20),
    ],
    "genres": [
        ("文芸小説", 4645), ("その他（要分類）", 261), ("児童学習漫画", 101),
        ("絵本・児童書", 78), ("時代小説・歴史小説", 56), ("児童文学", 56),
        ("ミステリ・推理", 54), ("実用・ハウツー", 47), ("児童学習書", 45),
        ("ファンタジー・SF", 31), ("絵本", 28), ("児童文学・YA", 24),
        ("翻訳小説", 13), ("エッセイ・評論", 8), ("社会・ノンフィクション", 7),
        ("英語絵本", 6), ("科学・学術", 5), ("恋愛・青春小説", 5),
    ],
    "age_groups": [
        ("一般（18歳以上）", 5096), ("小学生（6-12歳）", 202),
        ("幼児〜低学年（0-8歳）", 112), ("中高生以上（15歳以上）", 36),
        ("小学生〜中学生（8-15歳）", 24),
    ],
    "formats": [
        ("その他", 4477), ("文庫", 509), ("不明", 310),
        ("単行本", 158), ("ハードカバー", 9), ("新書", 5),
    ],
}

@app.route("/ping")
def ping():
    return "ok", 200


@app.route("/api/genres")
def api_genres():
    """ジャンル一覧と件数を返す"""
    return jsonify([
        {"genre": g, "count": len(books)}
        for g, books in sorted(GENRE_MAP.items(), key=lambda x: -len(x[1]))
    ])


@app.route("/api/books/by-genre")
def api_books_by_genre():
    """ジャンル別書籍一覧（ページネーション付き）"""
    genre = request.args.get("genre", "")
    page  = int(request.args.get("page", 1))
    per   = 50
    books = GENRE_MAP.get(genre, [])
    total = len(books)
    start = (page - 1) * per
    page_books = books[start:start + per]
    result = []
    for b in page_books:
        isbn13 = b["isbn"]
        isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
        cover  = get_cover_url(isbn13, isbn10)
        result.append({**b, "isbn10": isbn10, "cover": cover,
                       "rating": get_rating(isbn13)})
    return jsonify({"books": result, "total": total, "page": page, "genre": genre})


@app.route("/api/stats")
def api_stats():
    return jsonify(FULL_STATS)


@app.route("/api/today-book")
def api_today_book():
    import random, datetime
    today = datetime.date.today()
    seed = int(today.strftime("%Y%m%d"))
    rng = random.Random(seed)
    total_pages = 109
    page = rng.randint(1, total_pages)
    try:
        data = fetch_books("", page)
        if data["books"]:
            book = data["books"][rng.randint(0, len(data["books"]) - 1)]
            book["rating"] = get_rating(book["isbn"])
            return jsonify(book)
    except Exception:
        pass
    return jsonify(None)


@app.route("/api/books")
def api_books():
    keyword = request.args.get("keyword", "")
    page = int(request.args.get("page", 1))
    data = fetch_books(keyword, page)
    for book in data["books"]:
        book["rating"] = get_rating(book["isbn"])
    return jsonify(data)


@app.route("/api/book/<isbn>")
def api_book(isbn):
    detail = fetch_book_detail(isbn)
    detail["rating"] = get_rating(isbn)
    return jsonify(detail)


@app.route("/api/rate", methods=["POST"])
def api_rate():
    body = request.get_json()
    isbn = body.get("isbn", "")
    score = int(body.get("score", 0))
    review = body.get("review", "")
    if not isbn or score < 1 or score > 5:
        return jsonify({"error": "invalid"}), 400
    save_rating(isbn, score, review)
    return jsonify(get_rating(isbn))


@app.route("/api/library-info")
def api_library_info():
    return jsonify(LIBRARY_INFO)


@app.route("/api/announcements")
def api_announcements():
    con = get_con()
    rows = fetchall(con, "SELECT id, title, body, category, image_url, created_at FROM announcements ORDER BY id DESC")
    con.close()
    return jsonify([{**r, "image_url": r.get("image_url") or "", "created_at": str(r["created_at"])[:16]} for r in rows])


@app.route("/api/announcements", methods=["POST"])
def api_post_announcement():
    body = request.get_json()
    if body.get("password") != get_admin_password():
        return jsonify({"error": "unauthorized"}), 401
    title = body.get("title", "").strip()
    text = body.get("body", "").strip()
    if not title or not text:
        return jsonify({"error": "invalid"}), 400
    con = get_con()
    execute(con, "INSERT INTO announcements (title, body, category, image_url) VALUES (?,?,?,?)",
        (title, text, body.get("category","お知らせ"), body.get("image_url","").strip()))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    body = request.get_json()
    if body.get("password") != get_admin_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM announcements WHERE id=?", (ann_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Book Requests ---
@app.route("/api/requests")
def api_requests():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,author,reason,room,status,note,created_at FROM book_requests ORDER BY id DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@app.route("/api/requests", methods=["POST"])
def api_post_request():
    body = request.get_json()
    if body.get("password") not in (get_resident_password(), get_admin_password(), get_board_password()):
        return jsonify({"error": "unauthorized"}), 401
    title = body.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    con = get_con()
    execute(con, "INSERT INTO book_requests (title,author,reason,room) VALUES (?,?,?,?)",
        (title, body.get("author","").strip(), body.get("reason","").strip(), body.get("room","").strip()))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/requests/<int:req_id>", methods=["PATCH"])
def api_update_request(req_id):
    body = request.get_json()
    if body.get("password") != get_admin_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if "status" in body:
        execute(con, "UPDATE book_requests SET status=? WHERE id=?", (body["status"], req_id))
    if "note" in body:
        execute(con, "UPDATE book_requests SET note=? WHERE id=?", (body["note"], req_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/requests/<int:req_id>", methods=["DELETE"])
def api_delete_request(req_id):
    body = request.get_json()
    if body.get("password") != get_admin_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM book_requests WHERE id=?", (req_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Cloud Sync ---
@app.route("/api/user/login", methods=["POST"])
def api_user_login():
    body = request.get_json()
    room = (body.get("room") or "").strip()
    pin  = (body.get("pin")  or "").strip()
    if not room or not pin or len(pin) < 4:
        return jsonify({"error": "部屋番号と4桁以上のPINを入力してください"}), 400
    con = get_con()
    user = fetchone(con, "SELECT room, pin, favorites, reading_log FROM user_accounts WHERE room=?", (room,))
    if user is None:
        # 新規作成
        if USE_PG:
            execute(con, "INSERT INTO user_accounts (room, pin) VALUES (?,?)", (room, pin))
        else:
            execute(con, "INSERT INTO user_accounts (room, pin) VALUES (?,?)", (room, pin))
        con.commit(); con.close()
        return jsonify({"ok": True, "is_new": True, "favorites": [], "reading_log": {}})
    if user["pin"] != pin:
        con.close()
        return jsonify({"error": "PINが違います"}), 401
    con.close()
    return jsonify({
        "ok": True, "is_new": False,
        "favorites": json.loads(user["favorites"] or "[]"),
        "reading_log": json.loads(user["reading_log"] or "{}")
    })


@app.route("/api/user/sync", methods=["POST"])
def api_user_sync():
    body = request.get_json()
    room = (body.get("room") or "").strip()
    pin  = (body.get("pin")  or "").strip()
    if not room or not pin:
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    user = fetchone(con, "SELECT pin FROM user_accounts WHERE room=?", (room,))
    if not user or user["pin"] != pin:
        con.close()
        return jsonify({"error": "unauthorized"}), 401
    favs = json.dumps(body.get("favorites", []), ensure_ascii=False)
    rlog = json.dumps(body.get("reading_log", {}), ensure_ascii=False)
    if USE_PG:
        execute(con, "UPDATE user_accounts SET favorites=?, reading_log=?, updated_at=NOW() WHERE room=?",
                (favs, rlog, room))
    else:
        execute(con, "UPDATE user_accounts SET favorites=?, reading_log=?, updated_at=datetime('now','localtime') WHERE room=?",
                (favs, rlog, room))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Password change ---
@app.route("/api/admin/change-password", methods=["POST"])
def api_change_password():
    body = request.get_json()
    if body.get("current_password") != get_board_password():
        return jsonify({"error": "現在のパスワードが違います"}), 401
    target = body.get("target")
    new_pw = body.get("new_password", "").strip()
    if not new_pw or len(new_pw) < 4:
        return jsonify({"error": "4文字以上で入力してください"}), 400
    key_map = {"resident": "resident_password", "admin": "admin_password", "board": "board_password"}
    if target not in key_map:
        return jsonify({"error": "不正なターゲット"}), 400
    db_key = key_map[target]
    con = get_con()
    if USE_PG:
        execute(con, "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (db_key, new_pw))
    else:
        execute(con, "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (db_key, new_pw))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Quick availability check ---
@app.route("/api/availability/<isbn>")
def api_availability(isbn):
    """本の在架状況のみを高速取得（詳細ページをスクレイピング）"""
    try:
        url = f"{LIBRARYLIFE_BASE}/booksearch/detail/{isbn}"
        resp = requests.get(url, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        availability = []
        for row in soup.select("table.table tbody tr"):
            tds = row.find_all("td")
            if len(tds) >= 3 and tds[1].text.strip() and tds[2].text.strip():
                availability.append({"library": tds[1].text.strip(), "status": tds[2].text.strip()})
        if not availability:
            return jsonify({"status": "unknown"})
        # 在架があれば available、全て貸出中なら loaned
        statuses = [a["status"] for a in availability]
        if any(s in ("利用可能", "在架") for s in statuses):
            return jsonify({"status": "available", "items": availability})
        elif any("貸出中" in s for s in statuses):
            return jsonify({"status": "loaned", "items": availability})
        else:
            return jsonify({"status": "unknown", "items": availability})
    except Exception as e:
        return jsonify({"status": "error"}), 500


_ensure_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=(port == 5050), host="0.0.0.0", port=port)

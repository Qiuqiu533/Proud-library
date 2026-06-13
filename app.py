from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
import json
import os
import threading

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

_ADMIN_PASSWORD_ENV    = os.environ.get("ADMIN_PASSWORD",    "kanri5533")
_RESIDENT_PASSWORD_ENV = os.environ.get("RESIDENT_PASSWORD", "proudfunabashi")
_BOARD_PASSWORD_ENV    = os.environ.get("BOARD_PASSWORD",    "kanri5533")


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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS genre_books (
                isbn TEXT PRIMARY KEY,
                genre TEXT DEFAULT '',
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                format TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS availability_cache (
                isbn TEXT PRIMARY KEY,
                status TEXT,
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS genre_books (
                isbn TEXT PRIMARY KEY,
                genre TEXT DEFAULT '',
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                format TEXT DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS availability_cache (
                isbn TEXT PRIMARY KEY,
                status TEXT,
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
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
    threading.Thread(target=_migrate_genre_map_to_db, daemon=True).start()


def _migrate_genre_map_to_db():
    """genre_map.json が存在し DB が空なら一度だけ移行する"""
    try:
        con = get_con()
        row = fetchone(con, "SELECT COUNT(*) as cnt FROM genre_books")
        if row and row["cnt"] > 0:
            con.close()
            return  # 既にデータあり
        if not GENRE_MAP:
            con.close()
            return
        _insert_genre_books(con, GENRE_MAP)
        con.commit()
        con.close()
        print(f"genre_map.json → DB 移行完了")
    except Exception as e:
        print(f"genre migrate error: {e}")


def _insert_genre_books(con, genre_map):
    """ジャンルマップをDBに一括挿入（既存データは全削除してから）"""
    execute(con, "DELETE FROM genre_books")
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
            else:
                execute(con,
                    "INSERT OR REPLACE INTO genre_books (isbn,genre,title,author,publisher,format) VALUES (?,?,?,?,?,?)",
                    (isbn, genre, b.get("title",""), b.get("author",""), b.get("publisher",""), b.get("format","")))


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
    # キャッシュ保存（バックグラウンドで実行してレスポンスをブロックしない）
    if availability:
        statuses = [a["status"] for a in availability]
        if any(s in ("利用可能", "在架") for s in statuses):
            avail_status = "available"
        elif any("貸出中" in s for s in statuses):
            avail_status = "loaned"
        else:
            avail_status = "unknown"
        def _save_cache(isbn_, status_, title_, author_):
            try:
                c = get_con()
                if USE_PG:
                    execute(c, """INSERT INTO availability_cache (isbn, status, title, author, updated_at)
                        VALUES (%s,%s,%s,%s,NOW()) ON CONFLICT (isbn) DO UPDATE SET
                        status=EXCLUDED.status, title=EXCLUDED.title, author=EXCLUDED.author, updated_at=NOW()
                    """, (isbn_, status_, title_, author_))
                else:
                    execute(c, """INSERT OR REPLACE INTO availability_cache (isbn, status, title, author, updated_at)
                        VALUES (?,?,?,?,datetime('now','localtime'))""", (isbn_, status_, title_, author_))
                c.commit(); c.close()
            except Exception:
                pass
        threading.Thread(target=_save_cache, args=(isbn, avail_status, result.get("title",""), result.get("author","")), daemon=True).start()
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


def get_ratings_bulk(isbns):
    """複数ISBNのレーティングを一括取得"""
    if not isbns:
        return {}
    con = get_con()
    placeholders = ",".join(["?" for _ in isbns])
    rows = fetchall(con, f"SELECT isbn, score, votes, reviews FROM ratings WHERE isbn IN ({placeholders})", tuple(isbns))
    con.close()
    result = {}
    for row in rows:
        result[row["isbn"]] = {"score": row["score"], "votes": row["votes"], "reviews": json.loads(row["reviews"])}
    return result


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
        ("文藝春秋", 550), ("講談社", 550), ("新潮社", 386), ("角川書店", 348),
        ("登録無し(ISBN無の為)", 321), ("朝日新聞社", 204), ("集英社", 194), ("幻冬舎", 182),
        ("小学館", 177), ("福音館書店", 163), ("偕成社", 132), ("光文社", 124),
        ("ポプラ社", 117), ("双葉社", 86), ("中央公論社", 83), ("岩崎書店", 70),
        ("早川書房", 67), ("PHP研究所", 67), ("学習研究社", 67), ("徳間書店", 59),
        ("永岡書店", 56), ("宝島社", 54), ("チャイルド本社", 52), ("童話館出版", 47),
        ("童心社", 43), ("岩波書店", 43), ("金の星社", 41), ("東京創元社", 41),
        ("河出書房新社", 40), ("角川春樹事務所", 39), ("鈴木出版", 34), ("実業之日本社", 33),
        ("祥伝社", 29), ("フレーベル館", 27), ("しののめ出版", 27), ("主婦の友社", 25),
        ("こぐま社", 23), ("くもん出版", 22), ("筑摩書房", 22), ("日本図書センター", 21),
        ("あかね書房", 19), ("文化出版局", 16), ("ほるぷ出版", 15), ("ダイヤモンド社", 15),
        ("あすなろ書房", 15), ("スターツ出版", 14), ("教育画劇", 14), ("小峰書店", 14),
        ("ひさかたチャイルド", 14), ("成美堂出版", 13),
    ],
    "authors": [
        ("平岩 弓枝", 74), ("宮部 みゆき", 64), ("東野 圭吾", 55), ("塩野 七生", 55),
        ("韓 賢東", 52), ("佐伯 泰英", 50), ("藤沢 周平", 47), ("洪 在徹", 42),
        ("司馬 遼太郎", 41), ("山本 博文", 30), ("池波 正太郎", 27), ("村上 春樹", 26),
        ("百田 尚樹", 26), ("今野 敏", 25), ("上橋 菜穂子", 25), ("柚月 裕子", 25),
        ("あさの あつこ", 24), ("廣嶋 玲子", 23), ("有賀 忍", 21), ("尾道 理子", 19),
        ("恩田 陸", 19), ("ダン・ブラウン", 18), ("石田 衣良", 18), ("岡本 さとる", 18),
        ("青山 剛昌", 18), ("横山 秀夫", 17), ("赤川 次郎", 17), ("山崎 豊子", 17),
        ("誉田 哲也", 17), ("藤原 緋沙子", 17), ("原田 マハ", 17), ("北方 謙三", 17),
        ("浅田 次郎", 16), ("阿部 智里", 16), ("トロル", 16), ("松本 清張", 16),
        ("堂場 瞬一", 15), ("なかや みわ", 15), ("池井戸 潤", 15), ("内田 樹", 15),
        ("村山 由佳", 14), ("黒川 博行", 14), ("奥田 英朗", 14), ("椎名 誠", 13),
        ("有川 浩", 13), ("伊坂 幸太郎", 12), ("桐野 夏生", 12), ("斉藤 洋", 12),
        ("内田 康夫", 12), ("道尾 秀介", 11),
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
    """ジャンル一覧と件数を返す（DBから）"""
    con = get_con()
    rows = fetchall(con, "SELECT genre, COUNT(*) as cnt FROM genre_books GROUP BY genre ORDER BY cnt DESC")
    con.close()
    return jsonify([{"genre": r["genre"], "count": r["cnt"]} for r in rows])


@app.route("/api/books/by-genre")
def api_books_by_genre():
    """ジャンル別書籍一覧（DBから・ページネーション付き）"""
    genre = request.args.get("genre", "")
    page  = int(request.args.get("page", 1))
    per   = 50
    offset = (page - 1) * per
    con = get_con()
    total_row = fetchone(con, "SELECT COUNT(*) as cnt FROM genre_books WHERE genre=?", (genre,))
    total = total_row["cnt"] if total_row else 0
    rows = fetchall(con, "SELECT isbn,genre,title,author,publisher,format FROM genre_books WHERE genre=? LIMIT ? OFFSET ?",
                    (genre, per, offset))
    con.close()
    isbns = [b["isbn"] for b in rows]
    ratings = get_ratings_bulk(isbns)
    result = []
    for b in rows:
        isbn13 = b["isbn"]
        isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
        cover  = get_cover_url(isbn13, isbn10)
        result.append({**b, "isbn10": isbn10, "cover": cover, "rating": ratings.get(isbn13, {"score": 0, "votes": 0, "reviews": []})})
    return jsonify({"books": result, "total": total, "page": page, "genre": genre})




@app.route("/api/stats")
def api_stats():
    return jsonify(FULL_STATS)


@app.route("/api/books/new")
def api_books_new():
    """出版日順の新着100冊（OpenBD一括取得でソート）"""
    try:
        # librarylife から2ページ分取得
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(fetch_books, "", 1)
            f2 = ex.submit(fetch_books, "", 2)
            data1 = f1.result()
            data2 = f2.result()
        books = data1["books"] + data2["books"]

        # ISBNリストを作成（ISBN13のみ）
        isbns = [b["isbn"] for b in books if b.get("isbn") and len(b["isbn"]) == 13]

        # OpenBD 一括取得
        ob_resp = requests.get(OPENBD_API, params={"isbn": ",".join(isbns)}, timeout=10)
        ob_data = ob_resp.json()

        # isbn -> pubdate マップ作成
        pubdate_map = {}
        for item in ob_data:
            if not item:
                continue
            summary = item.get("summary", {})
            isbn = summary.get("isbn", "")
            pubdate = summary.get("pubdate", "")
            if isbn and pubdate:
                pubdate_map[isbn] = pubdate

        # 出版日をbookに付与
        for b in books:
            b["pubdate"] = pubdate_map.get(b["isbn"], "")

        # 出版日降順ソート（不明は末尾）
        books.sort(key=lambda b: b.get("pubdate") or "0", reverse=True)

        return jsonify({"books": books[:100]})
    except Exception as e:
        return jsonify({"books": [], "error": str(e)}), 500


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
    isbns = [b["isbn"] for b in data["books"] if b.get("isbn")]
    ratings = get_ratings_bulk(isbns)
    for book in data["books"]:
        book["rating"] = ratings.get(book["isbn"], {"score": 0, "votes": 0, "reviews": []})
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


# --- Bulk cache lookup (no scraping) ---
@app.route("/api/library-card-info")
def api_library_card_info():
    """librarylife.netの会員証URLから会員IDを取得"""
    url = request.args.get("url", "").strip()
    if not url or "librarylife.net/card/" not in url:
        return jsonify({"error": "librarylife.netの会員証URLを入力してください"}), 400
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        # 会員IDを探す（数字のみの要素、または "会員ID" ラベルの隣）
        member_id = ""
        # パターン1: テキストに「会員ID」や「会員番号」が含まれる要素の隣
        for el in soup.find_all(text=True):
            t = el.strip()
            if "会員ID" in t or "会員番号" in t or "Member" in t:
                parent = el.parent
                nxt = parent.find_next_sibling()
                if nxt and nxt.text.strip().isdigit():
                    member_id = nxt.text.strip()
                    break
                # 同じ要素内に数字があるか
                import re
                m = re.search(r'\d{7,12}', t)
                if m:
                    member_id = m.group()
                    break
        # パターン2: ページ全体から10桁程度の数字を探す
        if not member_id:
            import re
            text = soup.get_text()
            m = re.search(r'(?<!\d)(\d{10})(?!\d)', text)
            if m:
                member_id = m.group(1)
        # パターン3: バーコード画像のsrc
        barcode_url = ""
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "barcode" in src.lower() or "bar" in src.lower():
                barcode_url = src if src.startswith("http") else LIBRARYLIFE_BASE + src
                break
        if not member_id and not barcode_url:
            return jsonify({"error": "会員IDが見つかりませんでした。IDを直接入力してください"}), 404
        return jsonify({"member_id": member_id, "barcode_url": barcode_url})
    except Exception as e:
        return jsonify({"error": "読み込みに失敗しました。IDを直接入力してください"}), 500


@app.route("/api/availability/cached")
def api_availability_cached():
    """キャッシュ済みの在架状況を一括返却（スクレイピングなし）"""
    isbns_param = request.args.get("isbns", "")
    isbns = [i.strip() for i in isbns_param.split(",") if i.strip()]
    if not isbns:
        return jsonify({})
    con = get_con()
    try:
        placeholders = ",".join(["%s" if USE_PG else "?" for _ in isbns])
        rows = fetchall(con, f"SELECT isbn, status FROM availability_cache WHERE isbn IN ({placeholders})", tuple(isbns))
        con.close()
        return jsonify({r["isbn"]: r["status"] for r in rows})
    except Exception:
        con.close()
        return jsonify({})


# --- Quick availability check ---
@app.route("/api/availability/<isbn>")
def api_availability(isbn):
    """本の在架状況のみを高速取得（2時間以内のキャッシュがあればそれを返す）"""
    con = get_con()
    try:
        # キャッシュチェック（2時間以内）
        if USE_PG:
            cached = fetchone(con, "SELECT status, updated_at FROM availability_cache WHERE isbn=%s AND updated_at > NOW() - INTERVAL '2 hours'", (isbn,))
        else:
            cached = fetchone(con, "SELECT status, updated_at FROM availability_cache WHERE isbn=? AND updated_at > datetime('now','-2 hours','localtime')", (isbn,))
        if cached:
            con.close()
            return jsonify({"status": cached["status"], "cached": True})
    except Exception:
        pass

    # スクレイピング
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
            con.close()
            return jsonify({"status": "unknown"})
        statuses = [a["status"] for a in availability]
        if any(s in ("利用可能", "在架") for s in statuses):
            result_status = "available"
        elif any("貸出中" in s for s in statuses):
            result_status = "loaned"
        else:
            result_status = "unknown"

        # キャッシュ保存（title/authorはgenre_booksから取得）
        try:
            book_row = fetchone(con, "SELECT title, author FROM genre_books WHERE isbn=?", (isbn,))
            title = book_row["title"] if book_row else ""
            author = book_row["author"] if book_row else ""
            if USE_PG:
                execute(con, """
                    INSERT INTO availability_cache (isbn, status, title, author, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (isbn) DO UPDATE SET status=EXCLUDED.status, title=EXCLUDED.title, author=EXCLUDED.author, updated_at=NOW()
                """, (isbn, result_status, title, author))
            else:
                execute(con, """
                    INSERT OR REPLACE INTO availability_cache (isbn, status, title, author, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now','localtime'))
                """, (isbn, result_status, title, author))
            con.commit()
        except Exception:
            pass

        con.close()
        return jsonify({"status": result_status, "items": availability})
    except Exception:
        con.close()
        return jsonify({"status": "error"}), 500


@app.route("/api/availability/loaned")
def api_availability_loaned():
    """貸出中としてキャッシュされた書籍一覧（最新48時間）"""
    con = get_con()
    try:
        if USE_PG:
            rows = fetchall(con, """
                SELECT isbn, title, author, updated_at FROM availability_cache
                WHERE status='loaned' AND updated_at > NOW() - INTERVAL '48 hours'
                ORDER BY updated_at DESC
            """)
        else:
            rows = fetchall(con, """
                SELECT isbn, title, author, updated_at FROM availability_cache
                WHERE status='loaned' AND updated_at > datetime('now','-48 hours','localtime')
                ORDER BY updated_at DESC
            """)
        con.close()
        return jsonify(rows)
    except Exception as e:
        con.close()
        return jsonify([]), 500


# ── ジャンル自動分類 ──────────────────────────────────────────────────────

def _classify_genre(ndc, title="", description=""):
    """NDCコード＋キーワードでジャンルを自動判定"""
    combined = (title or "") + " " + (description or "")
    # キーワード優先（NDCより精度が高い）
    kw = {
        "ミステリ・推理":    ["ミステリ","推理","探偵","殺人事件","謎解き","サスペンス","刑事","犯罪"],
        "ファンタジー・SF":  ["ファンタジー","SF","魔法","異世界","宇宙","ロボット","タイムトラベル","ドラゴン"],
        "時代小説・歴史小説":["時代小説","歴史小説","江戸","武士","侍","幕府","戦国","剣客","忍者","藩"],
        "恋愛・青春小説":    ["恋愛小説","青春小説","ラブストーリー","純愛"],
        "エッセイ・評論":    ["エッセイ","随筆","評論","コラム"],
        "実用・ハウツー":    ["料理","レシピ","ダイエット","健康","投資","資産","育児","子育て","勉強法"],
        "社会・ノンフィクション": ["ノンフィクション","ルポ","ドキュメンタリー","事件","経済","政治","歴史的事件"],
    }
    for genre, words in kw.items():
        if any(w in combined for w in words):
            return genre
    # NDCコードで判定
    n = str(ndc or "")
    if n.startswith("726"):   return "絵本・児童書"
    if n.startswith("72"):    return "絵本・児童書"
    if n.startswith("916"):   return "エッセイ・評論"
    if n.startswith("913"):   return "文芸小説"
    if n.startswith("91"):    return "文芸小説"
    if n[:1] == "9":          return "翻訳小説"
    if n[:1] in ("4","5","6","0","1","2","3"):  return "実用・ハウツー"
    return "文芸小説"  # デフォルト


def _auto_classify_new_books():
    """バックグラウンド：新しい本を自動検出してジャンル分類（週1回）"""
    import time, datetime, threading

    def _run():
        try:
            # 前回更新から7日未満ならスキップ
            last = get_setting("genre_last_update", "")
            if last:
                try:
                    last_dt = datetime.datetime.fromisoformat(last)
                    if (datetime.datetime.now() - last_dt).days < 7:
                        print("ジャンル自動更新: 前回から7日未満のためスキップ")
                        return
                except Exception:
                    pass

            print("ジャンル自動更新: 開始...")
            # DB上の既知ISBNを取得
            con = get_con()
            rows = fetchall(con, "SELECT isbn FROM genre_books")
            con.close()
            known = {r["isbn"] for r in rows}

            # librarylife.net から全ISBNを収集
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
                    print(f"ジャンル自動更新: ページ{page}取得エラー {e}")
                    break

            if not new_books:
                print("ジャンル自動更新: 新しい本なし")
                _save_genre_update_time()
                return

            print(f"ジャンル自動更新: {len(new_books)}冊の新しい本を分類中...")

            # OpenBD で NDC コードを取得してジャンル分類
            batch_size = 100
            classified = 0
            for i in range(0, len(new_books), batch_size):
                batch = new_books[i:i + batch_size]
                isbns = [b["isbn"] for b in batch]
                ndc_map = {}
                desc_map = {}
                try:
                    resp = requests.get(OPENBD_API,
                                        params={"isbn": ",".join(isbns)}, timeout=15)
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
                    print(f"OpenBD バッチエラー: {e}")

                con = get_con()
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
                            "VALUES (?,?,?,?,?,?) ON CONFLICT(isbn) DO NOTHING",
                            (isbn, genre, b.get("title",""), b.get("author",""),
                             b.get("publisher",""), b.get("format","")))
                    else:
                        execute(con,
                            "INSERT OR IGNORE INTO genre_books "
                            "(isbn,genre,title,author,publisher,format) VALUES (?,?,?,?,?,?)",
                            (isbn, genre, b.get("title",""), b.get("author",""),
                             b.get("publisher",""), b.get("format","")))
                    classified += 1
                con.commit(); con.close()
                time.sleep(0.5)

            _save_genre_update_time()
            print(f"ジャンル自動更新: 完了 ({classified}冊追加)")
        except Exception as e:
            print(f"ジャンル自動更新エラー: {e}")

    threading.Thread(target=_run, daemon=True).start()


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
        print(f"_save_genre_update_time error: {e}")


_ensure_db()
_auto_classify_new_books()   # バックグラウンドで週1回実行

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=(port == 5050), host="0.0.0.0", port=port)

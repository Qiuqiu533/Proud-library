from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
import sqlite3
import json
import os

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# Initialize DB on import (works with gunicorn)
def _ensure_db():
    try:
        init_db()
    except Exception as e:
        print(f"DB init error: {e}")
LIBRARY_CODE = "0011"
LIBRARYLIFE_BASE = "https://www2.librarylife.net"
OPENBD_API = "https://api.openbd.jp/v1/get"
NDL_THUMB = "https://ndlsearch.ndl.go.jp/thumbnail/{isbn}.jpg"

# Opening hours (edit as needed)
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


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "proud2024")
RESIDENT_PASSWORD = os.environ.get("RESIDENT_PASSWORD", "proudfunabashi")
BOARD_PASSWORD = os.environ.get("BOARD_PASSWORD", "board2025")

def init_db():
    con = sqlite3.connect(DB_PATH)
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
    # Add image_url column if upgrading from old schema
    try:
        con.execute("ALTER TABLE announcements ADD COLUMN image_url TEXT DEFAULT ''")
        con.commit()
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
    # Add sort_order column if upgrading from old schema
    for tbl in ("issues", "calendar_events"):
        try:
            con.execute(f"ALTER TABLE {tbl} ADD COLUMN sort_order INTEGER DEFAULT 0")
            con.commit()
        except Exception:
            pass
    con.commit()
    con.close()


def get_cover_url(isbn13: str, isbn10: str = "") -> str:
    # Try NDL thumbnail first, fall back to Amazon
    ndl = NDL_THUMB.format(isbn=isbn13)
    if isbn10:
        amazon = f"https://images-na.ssl-images-amazon.com/images/P/{isbn10}.09.LZZZZZZZ.jpg"
        return amazon
    return ndl


def isbn13_to_isbn10(isbn13: str) -> str:
    """Convert ISBN-13 (978...) to ISBN-10."""
    if not isbn13 or not isbn13.startswith("978") or len(isbn13) < 13:
        return ""
    digits = isbn13[3:12]
    total = sum((10 - i) * int(d) for i, d in enumerate(digits))
    check = (11 - (total % 11)) % 11
    check_char = "X" if check == 10 else str(check)
    return digits + check_char


def fetch_books(keyword="", page=1):
    url = f"{LIBRARYLIFE_BASE}/booksearch"
    params = {"location": LIBRARY_CODE, "keyword": keyword, "page": page}
    resp = requests.get(url, params=params, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Total count
    page_data = soup.select_one(".page-data")
    total = 0
    if page_data:
        strong = page_data.find("strong")
        if strong:
            total = int(strong.text.replace(",", ""))

    books = []
    rows = soup.select("table.table tr")[1:]  # skip header
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        title_a = cols[0].find("a")
        author_a = cols[1].find("a")
        title = title_a.text.strip() if title_a else ""
        href = title_a["href"] if title_a else ""
        isbn = href.split("/")[-1] if href else ""
        author = author_a.text.strip() if author_a else ""
        publisher = cols[2].text.strip()
        fmt = cols[3].text.strip()

        isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
        cover = get_cover_url(isbn, isbn10)

        books.append({
            "isbn": isbn,
            "isbn10": isbn10,
            "title": title,
            "author": author,
            "publisher": publisher,
            "format": fmt,
            "cover": cover,
        })

    return {"books": books, "total": total, "page": page}


def fetch_book_detail(isbn: str):
    url = f"{LIBRARYLIFE_BASE}/booksearch/detail/{isbn}"
    resp = requests.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    result = {"isbn": isbn}
    result["title"] = soup.find("h1").text.strip() if soup.find("h1") else ""

    # Parse detail table
    rows = soup.select("#detail-area table.table tbody tr")
    for row in rows:
        ths = row.find_all("th")
        tds = row.find_all("td")
        for th, td in zip(ths, tds):
            key = th.text.strip()
            val = td.text.strip()
            if key == "著者":
                result["author"] = val
            elif key == "出版社":
                result["publisher"] = val
            elif key == "形式":
                result["format"] = val
            elif key == "出版年月日":
                result["pubdate"] = val
            elif key == "ISBN13":
                result["isbn13"] = val
            elif key == "ISBN10":
                result["isbn10"] = val
            elif key == "ページ数":
                result["pages"] = val

    # Availability
    status_rows = soup.select("table.table tbody tr")
    availability = []
    for row in status_rows:
        tds = row.find_all("td")
        if len(tds) >= 3:
            lib = tds[1].text.strip()
            status = tds[2].text.strip()
            if lib and status:
                availability.append({"library": lib, "status": status})
    result["availability"] = availability

    # Cover
    isbn10 = result.get("isbn10", "")
    isbn13 = result.get("isbn13", isbn)
    result["cover"] = get_cover_url(isbn13, isbn10)

    # Enrich with OpenBD
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
                # Description from onix
                onix = ob[0].get("onix", {})
                collateral = onix.get("CollateralDetail", {})
                texts = collateral.get("TextContent", [])
                for t in texts:
                    if t.get("TextType") in ("02", "03", "04"):
                        result["description"] = t.get("Text", "")
                        break
        except Exception:
            pass

    return result


def get_rating(isbn: str):
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT score, votes, reviews FROM ratings WHERE isbn=?", (isbn,)).fetchone()
    con.close()
    if row:
        return {"score": row[0], "votes": row[1], "reviews": json.loads(row[2])}
    return {"score": 0, "votes": 0, "reviews": []}


def save_rating(isbn: str, score: int, review: str = ""):
    con = sqlite3.connect(DB_PATH)
    existing = con.execute("SELECT score, votes, reviews FROM ratings WHERE isbn=?", (isbn,)).fetchone()
    if existing:
        new_votes = existing[1] + 1
        new_score = round((existing[0] * existing[1] + score) / new_votes, 1)
        reviews = json.loads(existing[2])
        if review:
            reviews.append(review)
        con.execute(
            "UPDATE ratings SET score=?, votes=?, reviews=? WHERE isbn=?",
            (new_score, new_votes, json.dumps(reviews, ensure_ascii=False), isbn),
        )
    else:
        reviews = [review] if review else []
        con.execute(
            "INSERT INTO ratings (isbn, score, votes, reviews) VALUES (?,?,?,?)",
            (isbn, float(score), 1, json.dumps(reviews, ensure_ascii=False)),
        )
    con.commit()
    con.close()


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth", methods=["POST"])
def api_auth():
    body = request.get_json()
    if body.get("password") == RESIDENT_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401


@app.route("/api/board/auth", methods=["POST"])
def api_board_auth():
    body = request.get_json()
    if body.get("password") == BOARD_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401


# --- Issues ---
@app.route("/api/issues")
def api_issues():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT id,title,body,priority,status,sort_order,created_at FROM issues ORDER BY sort_order ASC, id DESC").fetchall()
    con.close()
    return jsonify([{"id":r[0],"title":r[1],"body":r[2],"priority":r[3],"status":r[4],"sort_order":r[5],"created_at":r[6]} for r in rows])

@app.route("/api/issues", methods=["POST"])
def api_post_issue():
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    # New items go to top (sort_order = min - 1)
    row = con.execute("SELECT MIN(sort_order) FROM issues").fetchone()
    new_order = (row[0] or 0) - 1
    con.execute("INSERT INTO issues (title,body,priority,status,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("body","").strip(),
         body.get("priority","中"), body.get("status","未対応"), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/issues/reorder", methods=["POST"])
def api_reorder_issues():
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    for item in body.get("order", []):
        con.execute("UPDATE issues SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/issues/<int:issue_id>", methods=["PATCH"])
def api_update_issue(issue_id):
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    # Full edit
    if "title" in body:
        con.execute("UPDATE issues SET title=?,body=?,priority=?,status=? WHERE id=?",
            (body["title"], body.get("body",""), body.get("priority","中"), body.get("status","未対応"), issue_id))
    elif "status" in body:
        con.execute("UPDATE issues SET status=? WHERE id=?", (body["status"], issue_id))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/issues/<int:issue_id>", methods=["DELETE"])
def api_delete_issue(issue_id):
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM issues WHERE id=?", (issue_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Calendar ---
@app.route("/api/calendar")
def api_calendar():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT id,title,event_date,body,minutes,sort_order,created_at FROM calendar_events ORDER BY sort_order ASC, event_date DESC").fetchall()
    con.close()
    return jsonify([{"id":r[0],"title":r[1],"event_date":r[2],"body":r[3],"minutes":r[4],"sort_order":r[5],"created_at":r[6]} for r in rows])

@app.route("/api/calendar", methods=["POST"])
def api_post_calendar():
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT MIN(sort_order) FROM calendar_events").fetchone()
    new_order = (row[0] or 0) - 1
    con.execute("INSERT INTO calendar_events (title,event_date,body,minutes,sort_order) VALUES (?,?,?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), new_order))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/calendar/reorder", methods=["POST"])
def api_reorder_calendar():
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    for item in body.get("order", []):
        con.execute("UPDATE calendar_events SET sort_order=? WHERE id=?", (item["sort_order"], item["id"]))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/calendar/<int:ev_id>", methods=["PATCH"])
def api_update_calendar(ev_id):
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE calendar_events SET title=?,event_date=?,body=?,minutes=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""),
         body.get("body","").strip(), body.get("minutes","").strip(), ev_id))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/calendar/<int:ev_id>", methods=["DELETE"])
def api_delete_calendar(ev_id):
    body = request.get_json()
    if body.get("password") != BOARD_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM calendar_events WHERE id=?", (ev_id,))
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

@app.route("/api/stats")
def api_stats():
    return jsonify(FULL_STATS)


@app.route("/api/books")
def api_books():
    keyword = request.args.get("keyword", "")
    page = int(request.args.get("page", 1))
    data = fetch_books(keyword, page)
    # Attach ratings
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
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT id, title, body, category, image_url, created_at FROM announcements ORDER BY id DESC"
    ).fetchall()
    con.close()
    return jsonify([
        {"id": r[0], "title": r[1], "body": r[2], "category": r[3], "image_url": r[4] or "", "created_at": r[5]}
        for r in rows
    ])


@app.route("/api/announcements", methods=["POST"])
def api_post_announcement():
    body = request.get_json()
    if body.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    title = body.get("title", "").strip()
    text = body.get("body", "").strip()
    category = body.get("category", "お知らせ")
    image_url = body.get("image_url", "").strip()
    if not title or not text:
        return jsonify({"error": "invalid"}), 400
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO announcements (title, body, category, image_url) VALUES (?,?,?,?)",
        (title, text, category, image_url)
    )
    con.commit()
    con.close()
    return jsonify({"ok": True})


@app.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    body = request.get_json()
    if body.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True})


_ensure_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=(port == 5050), host="0.0.0.0", port=port)

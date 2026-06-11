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

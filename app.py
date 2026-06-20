from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
import json
import os
import threading
import time
from collections import defaultdict

# ── ジャンル別蔵書データ（Excelから事前生成）──────────────────────────────
_GENRE_MAP_PATH = os.path.join(os.path.dirname(__file__), "static", "genre_map.json")
try:
    with open(_GENRE_MAP_PATH, encoding="utf-8") as _f:
        GENRE_MAP = json.load(_f)
except Exception:
    GENRE_MAP = {}

app = Flask(__name__)

# ── レートリミット（住民向け公開エンドポイント保護）─────────────────────────
_rate_store = defaultdict(list)
_rate_lock = threading.Lock()

def _check_rate_limit(key, limit=5, window=60):
    """True=通過OK, False=制限超過。key単位でwindow秒間にlimit回まで許可。"""
    now = time.time()
    with _rate_lock:
        timestamps = _rate_store[key]
        timestamps[:] = [t for t in timestamps if now - t < window]
        if len(timestamps) >= limit:
            return False
        timestamps.append(now)
        return True

def rate_limit(limit=5, window=60):
    """デコレータ: IPアドレス＋エンドポイントでレートリミット"""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
            key = f"{ip}:{f.__name__}"
            if not _check_rate_limit(key, limit, window):
                return jsonify({"error": "しばらく時間をおいてから再試行してください"}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator

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
LIBRARYLIFE_BASE = "https://www.librarylife.net"
_INERTIA_VERSION = "e2ba382f0f96863d6a3cbb3f36f44b4e"
_INERTIA_SESSION = requests.Session()

def _refresh_inertia_version():
    """librarylife.netからInertiaバージョンを取得して更新する"""
    global _INERTIA_VERSION
    try:
        resp = _INERTIA_SESSION.get(f"{LIBRARYLIFE_BASE}/", timeout=10)
        import re as _re2
        m = _re2.search(r'"version":"([a-f0-9]{32})"', resp.text)
        if m:
            _INERTIA_VERSION = m.group(1)
            app.logger.info(f"Inertia version updated: {_INERTIA_VERSION}")
    except Exception as e:
        app.logger.error(f"_refresh_inertia_version error: {e}")
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

_ADMIN_PASSWORD_ENV    = os.environ.get("ADMIN_PASSWORD",    "")
_RESIDENT_PASSWORD_ENV = os.environ.get("RESIDENT_PASSWORD", "")
_BOARD_PASSWORD_ENV    = os.environ.get("BOARD_PASSWORD",    "")


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
        try:
            cur.execute("ALTER TABLE announcements ADD COLUMN event_date TEXT DEFAULT ''")
            con.commit()
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE genre_books ADD COLUMN description TEXT DEFAULT ''")
            con.commit()
        except Exception:
            pass
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
                library_card_url TEXT DEFAULT '',
                library_card_image TEXT DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS new_arrivals (
                id SERIAL PRIMARY KEY,
                isbn TEXT NOT NULL,
                arrived_at DATE NOT NULL,
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                cover TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staff_chat (
                id SERIAL PRIMARY KEY,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
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
        try:
            con.execute("ALTER TABLE announcements ADD COLUMN event_date TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE genre_books ADD COLUMN description TEXT DEFAULT ''")
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
                library_card_url TEXT DEFAULT '',
                library_card_image TEXT DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS new_arrivals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isbn TEXT NOT NULL,
                arrived_at TEXT NOT NULL,
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                cover TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS staff_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()
    con.close()


def _migrate_add_card_columns():
    """user_accounts に library_card_url/image カラムを追加（既存DBへの後付け）"""
    try:
        con = get_con()
        if USE_PG:
            for col in ("library_card_url", "library_card_image"):
                try:
                    con.cursor().execute(f"ALTER TABLE user_accounts ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    pass
        else:
            for col in ("library_card_url", "library_card_image"):
                try:
                    con.execute(f"ALTER TABLE user_accounts ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    pass
        con.close()
    except Exception as e:
        print(f"card column migration error: {e}")

NDC_TO_GENRE = {
    # 日本文学
    "913": "文芸小説", "915": "文芸小説",
    "914": "エッセイ・評論", "916": "エッセイ・評論", "917": "エッセイ・評論",
    "911": "文芸小説",  # 詩
    "912": "文芸小説",  # 戯曲
    # 時代・歴史小説
    "9131": "時代小説・歴史小説",  # 日本小説（江戸以前テーマ多い）
    # ミステリ
    "936": "ミステリ・推理",
    # 翻訳小説（各国文学）
    "920": "翻訳小説", "921": "翻訳小説", "922": "翻訳小説", "923": "翻訳小説",
    "930": "翻訳小説", "931": "翻訳小説", "932": "翻訳小説", "933": "翻訳小説",
    "934": "翻訳小説", "935": "翻訳小説", "937": "翻訳小説", "938": "翻訳小説",
    "940": "翻訳小説", "941": "翻訳小説", "942": "翻訳小説", "943": "翻訳小説",
    "950": "翻訳小説", "951": "翻訳小説", "953": "翻訳小説", "955": "翻訳小説",
    "960": "翻訳小説", "961": "翻訳小説", "963": "翻訳小説",
    "970": "翻訳小説", "971": "翻訳小説", "973": "翻訳小説",
    "980": "翻訳小説", "981": "翻訳小説", "983": "翻訳小説",
    "990": "翻訳小説", "993": "翻訳小説",
    # ファンタジー・SF（NDCでは小説内サブジャンルなので書名で補完）
    # 絵本・児童
    "726": "絵本・児童書", "E": "絵本・児童書",
    "Y8": "絵本・児童書", "Y81": "絵本・児童書", "Y82": "絵本・児童書",
    "Y9": "児童文学", "Y91": "児童文学", "Y92": "児童文学",
    # 自己啓発・ビジネス
    "159": "実用・ハウツー",  # 人生訓
    "336": "実用・ハウツー",  # 経営管理
    "335": "実用・ハウツー",  # 企業・経営
    "320": "実用・ハウツー",  # 法律
    "330": "実用・ハウツー",  # 経済
    "331": "実用・ハウツー",  # 経済学
    "338": "実用・ハウツー",  # 金融
    "141": "実用・ハウツー",  # 心理学
    "143": "実用・ハウツー",  # 発達心理
    "145": "実用・ハウツー",  # 異常心理
    "146": "実用・ハウツー",  # 臨床心理
    # 健康・医療
    "490": "実用・ハウツー", "491": "実用・ハウツー", "492": "実用・ハウツー",
    "493": "実用・ハウツー", "494": "実用・ハウツー", "495": "実用・ハウツー",
    "496": "実用・ハウツー", "497": "実用・ハウツー", "498": "実用・ハウツー",
    # 料理・生活
    "596": "実用・ハウツー",  # 料理
    "590": "実用・ハウツー",  # 家政
    "591": "実用・ハウツー",  # 家庭管理
    "593": "実用・ハウツー",  # 被服
    "597": "実用・ハウツー",  # 住居
    "598": "実用・ハウツー",  # 家庭衛生
    "370": "実用・ハウツー",  # 教育
    # 歴史・伝記
    "210": "エッセイ・評論", "211": "エッセイ・評論", "212": "エッセイ・評論",
    "213": "エッセイ・評論", "214": "エッセイ・評論", "215": "エッセイ・評論",
    "216": "エッセイ・評論", "217": "エッセイ・評論", "218": "エッセイ・評論",
    "219": "エッセイ・評論",
    "280": "エッセイ・評論", "281": "エッセイ・評論", "289": "エッセイ・評論",
    "230": "エッセイ・評論",  # 世界史
    # 社会・ノンフィクション
    "300": "エッセイ・評論", "304": "エッセイ・評論",
    "360": "エッセイ・評論", "361": "エッセイ・評論",
    "316": "エッセイ・評論",  # 民族問題
}

# タイトル・著者キーワードによる補完分類
KEYWORD_GENRE = [
    (["ミステリ","推理","刑事","探偵","殺人","犯罪","謎","サスペンス"], "ミステリ・推理"),
    (["時代","武士","侍","江戸","幕末","忍者","剣客","藩","お城","将軍"], "時代小説・歴史小説"),
    (["SF","宇宙","ロボット","人工知能","AI","未来","サイバー"], "ファンタジー・SF"),
    (["ファンタジー","魔法","魔王","勇者","異世界","竜","ドラゴン","エルフ"], "ファンタジー・SF"),
    (["絵本","えほん","ピクチャー"], "絵本・児童書"),
    (["児童","こども","子ども","少年","少女"], "児童文学"),
    (["料理","レシピ","クッキング","おかず","献立"], "実用・ハウツー"),
    (["健康","ダイエット","医療","病気","症状","治療","養生"], "実用・ハウツー"),
    (["ビジネス","仕事術","マネジメント","リーダー","起業","投資","株","マーケ"], "実用・ハウツー"),
    (["自己啓発","習慣","成功","メンタル","マインド","思考法"], "実用・ハウツー"),
]

def _ndc_to_genre(ndc):
    if not ndc:
        return ""
    # 長いプレフィックスから順にマッチ（より具体的なものを優先）
    for length in [4, 3, 2]:
        prefix = ndc[:length]
        if prefix in NDC_TO_GENRE:
            return NDC_TO_GENRE[prefix]
    return ""

def _keyword_genre(title, author=""):
    text = (title or "") + " " + (author or "")
    for keywords, genre in KEYWORD_GENRE:
        if any(kw in text for kw in keywords):
            return genre
    return ""

def _migrate_ndc_genres():
    """OpenBD NDCコード＋キーワードでジャンル未分類の本を自動分類（改訂版で再実行）"""
    import datetime
    CURRENT_VERSION = "v2"
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='ndc_classify_done'")
        if done and done["value"] == CURRENT_VERSION:
            con.close()
            return
        # 全件対象（未分類 + 前バージョン分類済みも再分類）
        rows = fetchall(con, "SELECT isbn, title, author FROM genre_books")
        con.close()
        if not rows:
            return
        # キーワードで先に補完（OpenBD不要な分）
        kw_updated = 0
        con_kw = get_con()
        for r in rows:
            genre = _keyword_genre(r["title"] or "", r["author"] or "")
            if genre:
                execute(con_kw, "UPDATE genre_books SET genre=? WHERE isbn=? AND (genre='' OR genre IS NULL OR genre='その他')", (genre, r["isbn"]))
                kw_updated += 1
        con_kw.commit(); con_kw.close()

        # OpenBD NDCコードで分類（未分類のみ）
        con2 = get_con()
        unclassified = fetchall(con2, "SELECT isbn FROM genre_books WHERE genre='' OR genre IS NULL OR genre='その他'")
        con2.close()
        isbns = [r["isbn"] for r in unclassified if r["isbn"]]
        ndc_updated = 0
        for i in range(0, len(isbns), 500):
            batch = isbns[i:i+500]
            try:
                resp = requests.get(OPENBD_API, params={"isbn": ",".join(batch)}, timeout=30)
                con3 = get_con()
                for item in resp.json():
                    if not item:
                        continue
                    try:
                        isbn = item["summary"].get("isbn", "")
                        title = item["summary"].get("title", "")
                        author = item["summary"].get("author", "")
                        subjects = item.get("onix", {}).get("DescriptiveDetail", {}).get("Subject", [])
                        ndc = next((s["SubjectCode"] for s in subjects if s.get("SubjectSchemeIdentifier") == "78"), "")
                        genre = _ndc_to_genre(ndc) or _keyword_genre(title, author)
                        if genre and isbn:
                            execute(con3, "UPDATE genre_books SET genre=? WHERE isbn=? AND (genre='' OR genre IS NULL OR genre='その他')", (genre, isbn))
                            ndc_updated += 1
                    except Exception:
                        pass
                con3.commit(); con3.close()
            except Exception as e:
                print(f"NDC batch error: {e}")

        # 完了フラグ（バージョン付き）
        con4 = get_con()
        if USE_PG:
            execute(con4, "INSERT INTO settings(key,value) VALUES('ndc_classify_done',?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (CURRENT_VERSION,))
        else:
            execute(con4, "INSERT OR REPLACE INTO settings(key,value) VALUES('ndc_classify_done',?)", (CURRENT_VERSION,))
        con4.commit(); con4.close()
        print(f"NDC genre classification v2: keyword={kw_updated}, ndc={ndc_updated} books updated")
    except Exception as e:
        print(f"NDC classify error: {e}")

def _ensure_db():
    try:
        init_db()
    except Exception as e:
        print(f"DB init error: {e}")
    threading.Thread(target=_migrate_add_card_columns, daemon=True).start()
    threading.Thread(target=_migrate_genre_map_to_db, daemon=True).start()
    threading.Thread(target=_migrate_ndc_genres, daemon=True).start()
    threading.Thread(target=_migrate_add_votes_column, daemon=True).start()
    threading.Thread(target=_migrate_add_type_reply_columns, daemon=True).start()
    threading.Thread(target=_migrate_add_staff_chat, daemon=True).start()
    threading.Thread(target=_migrate_lib_schedule, daemon=True).start()


def _migrate_add_staff_chat():
    try:
        con = get_con()
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS staff_chat (
                    id SERIAL PRIMARY KEY,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    image_data TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # 既存テーブルにimage_dataカラムを追加
            try:
                cur.execute("ALTER TABLE staff_chat ADD COLUMN image_data TEXT DEFAULT ''")
            except Exception:
                con.rollback()
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS staff_chat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    image_data TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            try:
                con.execute("ALTER TABLE staff_chat ADD COLUMN image_data TEXT DEFAULT ''")
            except Exception:
                pass
        con.commit()
        con.close()
    except Exception as e:
        print(f"migrate staff_chat error: {e}")


def _migrate_add_votes_column():
    try:
        con = get_con()
        if USE_PG:
            try:
                con.cursor().execute("ALTER TABLE book_requests ADD COLUMN votes INTEGER DEFAULT 0")
                con.commit()
            except Exception:
                con.rollback()
        else:
            try:
                con.execute("ALTER TABLE book_requests ADD COLUMN votes INTEGER DEFAULT 0")
                con.commit()
            except Exception:
                pass
        con.close()
    except Exception as e:
        print(f"migrate votes error: {e}")

def _migrate_add_type_reply_columns():
    try:
        con = get_con()
        for col, default in [("type", "'request'"), ("reply", "''")]:
            try:
                if USE_PG:
                    con.cursor().execute(f"ALTER TABLE book_requests ADD COLUMN {col} TEXT DEFAULT {default}")
                    con.commit()
                else:
                    con.execute(f"ALTER TABLE book_requests ADD COLUMN {col} TEXT DEFAULT {default}")
                    con.commit()
            except Exception:
                if USE_PG: con.rollback()
        con.close()
    except Exception as e:
        print(f"migrate type/reply error: {e}")

def _migrate_lib_schedule():
    try:
        con = get_con()
        if USE_PG:
            con.cursor().execute("""
                CREATE TABLE IF NOT EXISTS lib_schedule (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'event',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS lib_schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'event',
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
        con.commit()
        con.close()
    except Exception as e:
        print(f"migrate lib_schedule error: {e}")

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


def _sync_awards_from_master(con, isbn, title, author):
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
        print(f"awards sync error: {e}")


def _insert_genre_books(con, genre_map):
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


def fetch_books(keyword="", page=1):
    url = f"{LIBRARYLIFE_BASE}/booksearch"
    params = {"location": LIBRARY_CODE, "keyword": keyword, "page": page}
    try:
        resp = _INERTIA_SESSION.get(url, params=params, timeout=10,
                                    headers=_inertia_headers("books", "book-search/index"))
        if resp.status_code == 409:
            _refresh_inertia_version()
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
        app.logger.error(f"fetch_books error: {e}")
        return {"books": [], "total": 0, "page": page}


def fetch_book_detail(isbn, hint_title=""):
    url = f"{LIBRARYLIFE_BASE}/booksearch/detail/{isbn}"
    result = {"isbn": isbn}
    availability = []
    try:
        resp = _INERTIA_SESSION.get(url, timeout=10,
                                    headers=_inertia_headers())
        if resp.status_code == 409:
            _refresh_inertia_version()
            resp = _INERTIA_SESSION.get(url, timeout=10,
                                        headers=_inertia_headers())
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
        # 在庫情報をstocksから生成
        availability = []
        for s in book.get("stocks", []):
            location = s.get("location", "")
            state = s.get("state", "")
            if location and state:
                availability.append({"library": location, "status": state})
        result["availability"] = availability
    except Exception as e:
        app.logger.error(f"fetch_book_detail error: {e}")
        result["availability"] = []
    # キャッシュ保存（バックグラウンドで実行してレスポンスをブロックしない）
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
    # DBの書評を取得（ISBNで引いた後タイトル検証、不一致ならタイトルで再検索）
    try:
        import re as _re
        dc = get_con()
        ph = "%s" if USE_PG else "?"
        # フロントエンドから渡されたタイトルを優先（図書館APIが失敗してもタイトル検証できる）
        lib_title = result.get("title", "").strip() or hint_title
        lib_author = result.get("author", "").strip()

        def _title_core(t):
            return _re.sub(r'[\s\(（【〈\[<＜].*', '', t).strip()

        def _title_match(t1, t2):
            if not t1 or not t2:
                return True
            c1, c2 = _title_core(t1), _title_core(t2)
            return c1 == c2 or c1 in t2 or c2 in t1 or c1 in c2 or c2 in c1

        cached = fetchone(dc, f"SELECT title, author, description, manual_review, manual_review_date, ai_review_date, ai_review_score, ai_model, helpful_count FROM genre_books WHERE isbn={ph}", (isbn,))

        # ISBNで見つかったがタイトルが一致しない場合 → タイトルで再検索
        if cached and cached.get("description") and lib_title:
            if not _title_match(lib_title, cached.get("title", "")):
                app.logger.warning(f"ISBN-title mismatch: isbn={isbn} lib='{lib_title}' db='{cached.get('title')}'")
                cached = None  # 使わない

        # ISBNで見つからない or タイトル不一致 → タイトルで再検索
        if (not cached or not cached.get("description")) and lib_title:
            cached = fetchone(dc,
                f"SELECT title, author, description, manual_review, manual_review_date, ai_review_date, ai_review_score, ai_model FROM genre_books WHERE title={ph}",
                (lib_title,))
            # 完全一致しない場合は前方一致で再試行
            if not cached or not cached.get("description"):
                title_prefix = _title_core(lib_title)
                if len(title_prefix) >= 4:
                    cached = fetchone(dc,
                        f"SELECT title, author, description, manual_review, manual_review_date, ai_review_date, ai_review_score, ai_model FROM genre_books WHERE title LIKE {ph}",
                        (title_prefix + "%",))

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
            ai_m = cached.get("ai_model")
            if ai_d:
                result["ai_review_date"] = str(ai_d)
            if ai_s:
                result["ai_review_score"] = int(ai_s)
            if ai_m:
                result["ai_model"] = ai_m
        if cached and result.get("description"):
            hc = cached.get("helpful_count")
            if hc:
                result["helpful_count"] = int(hc)
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
                # OpenBDの説明文はDBに書評がない場合のみ使用
                if not result.get("description"):
                    for t in ob[0].get("onix", {}).get("CollateralDetail", {}).get("TextContent", []):
                        if t.get("TextType") in ("02", "03", "04"):
                            result["description"] = t.get("Text", "")
                            break
        except Exception:
            pass
    # Google Books APIで説明文を補完（登録不要・無料）- キャッシュがない場合のみ
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
                    # DBにキャッシュ保存（バックグラウンド）
                    def _save_desc(isbn_, desc_, title_, author_, publisher_):
                        try:
                            dc = get_con()
                            ph = "%s" if USE_PG else "?"
                            # 既存の書評がある場合は上書きしない
                            existing = fetchone(dc, f"SELECT description FROM genre_books WHERE isbn={ph}", (isbn_,))
                            if existing and existing.get("description"):
                                dc.close()
                                return
                            if USE_PG:
                                execute(dc, """INSERT INTO genre_books (isbn, title, author, publisher, genre, format, description)
                                    VALUES (%s,%s,%s,%s,'その他','その他',%s)
                                    ON CONFLICT (isbn) DO UPDATE SET description=EXCLUDED.description""",
                                    (isbn_, title_, author_, publisher_, desc_))
                            else:
                                execute(dc, "UPDATE genre_books SET description=? WHERE isbn=?", (desc_, isbn_))
                            dc.commit(); dc.close()
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
@rate_limit(limit=5, window=60)
def api_auth():
    body = request.get_json()
    if body.get("password") == get_resident_password():
        return jsonify({"ok": True})
    return jsonify({"error": "unauthorized"}), 401


@app.route("/api/login-qr-url")
def api_login_qr_url():
    base = request.host_url.rstrip("/")
    pw = get_resident_password()
    import urllib.parse
    qr_url = f"{base}/?qr={urllib.parse.quote(pw)}"
    return jsonify({"url": qr_url})


@app.route("/api/board/auth", methods=["POST"])
@rate_limit(limit=5, window=60)
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


# --- Lib Schedule ---
@app.route("/api/lib-schedule")
def api_lib_schedule():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,event_date,type,created_at FROM lib_schedule ORDER BY event_date ASC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10]} for r in rows])


@app.route("/api/lib-schedule", methods=["POST"])
def api_post_lib_schedule():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "INSERT INTO lib_schedule (title,event_date,type) VALUES (?,?,?)",
        (body.get("title","").strip(), body.get("event_date",""), body.get("type","event")))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/lib-schedule/<int:sch_id>", methods=["PATCH"])
def api_update_lib_schedule(sch_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "UPDATE lib_schedule SET title=?,event_date=?,type=? WHERE id=?",
        (body.get("title","").strip(), body.get("event_date",""), body.get("type","event"), sch_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/lib-schedule/<int:sch_id>", methods=["DELETE"])
def api_delete_lib_schedule(sch_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM lib_schedule WHERE id=?", (sch_id,))
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

def auto_cleanup_images():
    """DB使用量が95%超の場合、古い画像データを自動削除する"""
    if not USE_PG:
        return
    try:
        con = get_con()
        size_row = fetchone(con, "SELECT pg_database_size(current_database()) AS bytes")
        total_bytes = size_row["bytes"]
        limit_bytes = 512 * 1024 * 1024
        percent = total_bytes / limit_bytes * 100
        if percent >= 95:
            # チャット画像：古い順に最大50件の画像データを削除
            execute(con, """
                UPDATE staff_chat SET image_data = ''
                WHERE image_data != '' AND id IN (
                    SELECT id FROM staff_chat WHERE image_data != ''
                    ORDER BY created_at ASC LIMIT 50
                )
            """)
            # お知らせ画像：base64保存されている古い順に最大10件を削除
            execute(con, """
                UPDATE announcements SET image_url = ''
                WHERE image_url LIKE 'data:%' AND id IN (
                    SELECT id FROM announcements WHERE image_url LIKE 'data:%'
                    ORDER BY id ASC LIMIT 10
                )
            """)
            con.commit()
        con.close()
    except Exception as e:
        print(f"auto_cleanup_images error: {e}")

@app.route("/ping")
def ping():
    auto_cleanup_images()
    return "ok", 200


@app.route("/api/genres")
def api_genres():
    """ジャンル一覧と件数を返す（DBから）"""
    con = get_con()
    rows = fetchall(con, "SELECT genre, COUNT(*) as cnt FROM genre_books GROUP BY genre ORDER BY cnt DESC")
    con.close()
    return jsonify([{"genre": r["genre"], "count": r["cnt"]} for r in rows])


@app.route("/api/books/batch")
def api_books_batch():
    """ISBNリストをDBから一括取得（お気に入り・読書記録用）"""
    isbns_param = request.args.get("isbns", "")
    isbns = [i.strip() for i in isbns_param.split(",") if i.strip()][:50]
    if not isbns:
        return jsonify([])
    con = get_con()
    placeholders = ",".join(["?" for _ in isbns])
    rows = fetchall(con, f"SELECT isbn,title,author,publisher,format FROM genre_books WHERE isbn IN ({placeholders})", tuple(isbns))
    con.close()
    row_map = {r["isbn"]: r for r in rows}
    result = []
    for isbn in isbns:
        r = row_map.get(isbn)
        if r:
            isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
            result.append({**r, "cover": get_cover_url(isbn, isbn10), "rating": {"score":0,"votes":0,"reviews":[]}})
        else:
            result.append({"isbn": isbn, "title": isbn, "author": "", "publisher": "", "cover": "", "rating": {"score":0,"votes":0,"reviews":[]}})
    return jsonify(result)

@app.route("/api/books/by-genre")
def api_books_by_genre():
    """ジャンル別・全件・キーワード・受賞フィルターDB検索（ページネーション付き）"""
    genre   = request.args.get("genre", "")
    keyword = request.args.get("keyword", "").strip()
    award   = request.args.get("award", "").strip()  # 受賞フィルター
    page    = int(request.args.get("page", 1))
    per     = min(int(request.args.get("per", 50)), 200)
    offset  = (page - 1) * per
    con = get_con()
    ph = "%s" if USE_PG else "?"
    conditions = []
    params_base = []
    if genre:
        conditions.append(f"genre={ph}")
        params_base.append(genre)
    if keyword:
        like = f"%{keyword}%"
        conditions.append(f"(title LIKE {ph} OR author LIKE {ph})")
        params_base.extend([like, like])
    if award:
        if USE_PG:
            if award == "本屋大賞":
                # 1位〜10位すべて（本屋大賞 + 本屋大賞ノミネート）を含める
                conditions.append("(awards @> %s::jsonb OR awards @> %s::jsonb)")
                params_base.append(json.dumps([{"award": "本屋大賞"}]))
                params_base.append(json.dumps([{"award": "本屋大賞ノミネート"}]))
            else:
                conditions.append("awards @> %s::jsonb")
                params_base.append(json.dumps([{"award": award}]))
        else:
            conditions.append(f"awards LIKE {ph}")
            params_base.append(f"%{award}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params_count = tuple(params_base)
    params_rows  = tuple(params_base) + (per, offset)
    sql_count = f"SELECT COUNT(*) as cnt FROM genre_books {where}"
    sql_rows  = f"SELECT isbn,genre,title,author,publisher,format,awards FROM genre_books {where} ORDER BY isbn DESC LIMIT {ph} OFFSET {ph}"
    total_row = fetchone(con, sql_count, params_count)
    total = total_row["cnt"] if total_row else 0
    rows = fetchall(con, sql_rows, params_rows)
    con.close()
    isbns = [b["isbn"] for b in rows]
    ratings = get_ratings_bulk(isbns)
    result = []
    for b in rows:
        isbn13 = b["isbn"]
        isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
        cover  = get_cover_url(isbn13, isbn10)
        awards_val = b.get("awards") or []
        if isinstance(awards_val, str):
            try: awards_val = json.loads(awards_val)
            except: awards_val = []
        result.append({**b, "isbn10": isbn10, "cover": cover,
                       "awards": awards_val,
                       "rating": ratings.get(isbn13, {"score": 0, "votes": 0, "reviews": []})})
    return jsonify({"books": result, "total": total, "page": page, "genre": genre, "keyword": keyword, "award": award})




@app.route("/api/stats")
def api_stats():
    return jsonify(FULL_STATS)


@app.route("/api/new-arrivals")
def api_get_new_arrivals():
    con = get_con()
    rows = fetchall(con, "SELECT id,isbn,arrived_at,title,author,publisher,cover FROM new_arrivals ORDER BY arrived_at DESC, id DESC")
    con.close()
    return jsonify([{**r, "arrived_at": str(r["arrived_at"])[:10]} for r in rows])


@app.route("/api/new-arrivals", methods=["POST"])
def api_post_new_arrival():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    isbn = (body.get("isbn") or "").strip().replace("-", "")
    arrived_at = (body.get("arrived_at") or "").strip()
    if not isbn or not arrived_at:
        return jsonify({"error": "ISBN と入荷日は必須です"}), 400
    title = (body.get("title") or "").strip()
    author = (body.get("author") or "").strip()
    publisher = (body.get("publisher") or "").strip()
    cover = (body.get("cover") or "").strip()
    con = get_con()
    if USE_PG:
        execute(con, "INSERT INTO new_arrivals (isbn,arrived_at,title,author,publisher,cover) VALUES (?,?,?,?,?,?)",
                (isbn, arrived_at, title, author, publisher, cover))
    else:
        execute(con, "INSERT INTO new_arrivals (isbn,arrived_at,title,author,publisher,cover) VALUES (?,?,?,?,?,?)",
                (isbn, arrived_at, title, author, publisher, cover))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/new-arrivals/<int:arrival_id>", methods=["DELETE"])
def api_delete_new_arrival(arrival_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM new_arrivals WHERE id=?", (arrival_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/new-arrivals/lookup")
def api_new_arrival_lookup():
    isbn = request.args.get("isbn", "").strip().replace("-", "")
    if not isbn:
        return jsonify({"error": "ISBN required"}), 400
    try:
        resp = requests.get(OPENBD_API, params={"isbn": isbn}, timeout=8)
        data = resp.json()
        if data and data[0]:
            s = data[0]["summary"]
            isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
            return jsonify({
                "isbn": isbn,
                "title": s.get("title", ""),
                "author": s.get("author", ""),
                "publisher": s.get("publisher", ""),
                "cover": s.get("cover", "") or get_cover_url(isbn, isbn10)
            })
    except Exception:
        pass
    return jsonify({"isbn": isbn, "title": "", "author": "", "publisher": "", "cover": ""})


@app.route("/api/books/new")
def api_books_new():
    """新着図書一覧：new_arrivalsテーブル優先、なければOpenBD出版日順"""
    try:
        con = get_con()
        rows = fetchall(con, "SELECT isbn,arrived_at,title,author,publisher,cover FROM new_arrivals ORDER BY arrived_at DESC, id DESC LIMIT 100")
        con.close()
        if rows:
            books = []
            for r in rows:
                isbn = r["isbn"]
                isbn10 = isbn13_to_isbn10(isbn) if isbn.startswith("978") else ""
                books.append({
                    "isbn": isbn,
                    "isbn10": isbn10,
                    "title": r["title"] or isbn,
                    "author": r["author"] or "",
                    "publisher": r["publisher"] or "",
                    "cover": r["cover"] or get_cover_url(isbn, isbn10),
                    "arrived_at": str(r["arrived_at"])[:10],
                    "format": ""
                })
            return jsonify({"books": books, "source": "registered"})
    except Exception:
        pass
    # フォールバック：従来のOpenBD出版日順
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
        con = get_con()
        rows = fetchall(con, "SELECT isbn, title, author, publisher FROM genre_books")
        con.close()
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
        # DBに保存
        con2 = get_con()
        _upsert_setting(con2, "recent_books_cache", json.dumps(recent, ensure_ascii=False))
        _upsert_setting(con2, "recent_books_cache_date", str(today))
        con2.commit(); con2.close()
        _recent_isbns_cache["isbns"] = recent
        _recent_isbns_cache["date"] = today
        return recent
    except Exception as e:
        print(f"recent_isbns build error: {e}")
        return []

def get_recent_isbns():
    import datetime
    today = datetime.date.today()
    cache = _recent_isbns_cache
    # メモリキャッシュがあれば即返す
    if cache["date"] == today and cache["isbns"]:
        return cache["isbns"]
    # DBキャッシュを確認
    try:
        con = get_con()
        date_row = fetchone(con, "SELECT value FROM settings WHERE key='recent_books_cache_date'")
        if date_row and date_row["value"] == str(today):
            data_row = fetchone(con, "SELECT value FROM settings WHERE key='recent_books_cache'")
            con.close()
            if data_row:
                isbns = json.loads(data_row["value"])
                cache["isbns"] = isbns
                cache["date"] = today
                return isbns
        con.close()
    except Exception:
        pass
    # キャッシュ無し→バックグラウンドで構築、今回は空リストを返す
    threading.Thread(target=_build_recent_isbns, daemon=True).start()
    return cache.get("isbns", [])

@app.route("/api/today-book")
def api_today_book():
    import random, datetime
    today = datetime.date.today()
    seed = int(today.strftime("%Y%m%d"))
    rng = random.Random(seed)
    recent = get_recent_isbns()
    if recent:
        rng.shuffle(recent)
        books = recent[:8]
        # 表紙URLをISBNから直接生成（キャッシュの混在防止）
        for b in books:
            isbn = b.get("isbn", "")
            if isbn:
                isbn10 = isbn13_to_isbn10(isbn)
                b["cover"] = get_cover_url(isbn, isbn10)
        return jsonify(books)
    total_pages = 109
    page = rng.randint(1, total_pages)
    try:
        data = fetch_books("", page)
        if data["books"]:
            book = data["books"][rng.randint(0, len(data["books"]) - 1)]
            return jsonify([book])
    except Exception:
        pass
    return jsonify([])


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


@app.route("/api/books/no-review")
def api_books_no_review():
    """書評が未登録（NULLまたは空）の本一覧を返す"""
    con = get_con()
    rows = fetchall(con, """
        SELECT isbn, title, author FROM genre_books
        WHERE (description IS NULL OR description = '')
          AND manual_review IS NOT TRUE
        ORDER BY title
        LIMIT 200
    """)
    con2 = get_con()
    total_row = fetchone(con2, """
        SELECT COUNT(*) as cnt FROM genre_books
        WHERE (description IS NULL OR description = '')
          AND manual_review IS NOT TRUE
    """)
    con.close(); con2.close()
    return jsonify({"books": rows, "total": total_row["cnt"] if total_row else 0})


@app.route("/api/book/<isbn>")
def api_book(isbn):
    hint_title = request.args.get("title", "").strip()
    detail = fetch_book_detail(isbn, hint_title=hint_title)
    detail["rating"] = get_rating(isbn)
    # DBからawards取得
    con = get_con()
    row = fetchone(con, "SELECT awards FROM genre_books WHERE isbn=%s", (isbn,))
    con.close()
    awards = (row.get("awards") or []) if row else []
    if isinstance(awards, str):
        try: awards = json.loads(awards)
        except: awards = []
    detail["awards"] = awards
    return jsonify(detail)


@app.route("/api/book-description", methods=["POST"])
def api_book_description():
    body = request.get_json()
    password = body.get("password", "")
    if password != get_admin_password() and password != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    isbn = body.get("isbn", "").strip()
    description = body.get("description", "").strip()[:600]
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "UPDATE genre_books SET description=?, manual_review=TRUE, manual_review_date=CURRENT_DATE WHERE isbn=?", (description, isbn))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@app.route("/api/book-award", methods=["POST"])
def api_book_award():
    """受賞情報の設定（管理者のみ）"""
    body = request.get_json()
    password = body.get("password", "")
    if password != get_admin_password() and password != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    isbn = body.get("isbn", "").strip()
    awards = body.get("awards", [])  # [{award, year, type, rank}, ...]
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "UPDATE genre_books SET awards=%s WHERE isbn=%s", (json.dumps(awards, ensure_ascii=False), isbn))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@app.route("/api/book-awards/<isbn>")
def api_book_awards_get(isbn):
    """本の受賞情報取得"""
    con = get_con()
    row = fetchone(con, "SELECT awards FROM genre_books WHERE isbn=%s", (isbn,))
    con.close()
    if not row:
        return jsonify({"awards": []})
    awards = row.get("awards") or []
    if isinstance(awards, str):
        try: awards = json.loads(awards)
        except: awards = []
    return jsonify({"awards": awards})


@app.route("/api/awards/list")
def api_awards_list():
    """受賞情報がある本の一覧（フィルター用）"""
    con = get_con()
    if USE_PG:
        rows = fetchall(con, "SELECT isbn, title, author, awards FROM genre_books WHERE awards IS NOT NULL AND awards != '[]'::jsonb ORDER BY isbn DESC")
    else:
        rows = fetchall(con, "SELECT isbn, title, author, awards FROM genre_books WHERE awards IS NOT NULL AND awards != '[]' ORDER BY isbn DESC")
    con.close()
    result = []
    for r in rows:
        awards = r.get("awards") or []
        if isinstance(awards, str):
            try: awards = json.loads(awards)
            except: awards = []
        if awards:
            result.append({"isbn": r["isbn"], "title": r["title"], "author": r["author"], "awards": awards})
    return jsonify({"books": result})


@app.route("/api/books/related/<isbn>")
def api_books_related(isbn):
    """同じ著者・同じジャンルの本を返す（モーダル用）"""
    con = get_con()
    book = fetchone(con, "SELECT author, genre FROM genre_books WHERE isbn=?", (isbn,))
    if not book:
        con.close()
        return jsonify({"same_author": [], "same_genre": []})
    author = book["author"]
    genre = book["genre"]
    same_author = fetchall(con,
        "SELECT isbn, title, author FROM genre_books WHERE author=? AND isbn!=? ORDER BY isbn DESC LIMIT 20",
        (author, isbn))
    same_genre = fetchall(con,
        "SELECT isbn, title, author FROM genre_books WHERE genre=? AND isbn!=? AND (author!=? OR author IS NULL) ORDER BY isbn DESC LIMIT 20",
        (genre, isbn, author))
    con.close()
    def enrich(rows):
        result = []
        for b in rows:
            isbn13 = b["isbn"]
            isbn10 = isbn13_to_isbn10(isbn13) if isbn13.startswith("978") else ""
            result.append({"isbn": isbn13, "title": b["title"], "author": b["author"], "cover": get_cover_url(isbn13, isbn10)})
        return result
    return jsonify({"same_author": enrich(same_author), "same_genre": enrich(same_genre)})


@app.route("/api/helpful", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_helpful():
    body = request.get_json()
    isbn = body.get("isbn", "").strip()
    if not isbn:
        return jsonify({"error": "isbn required"}), 400
    con = get_con()
    execute(con, "UPDATE genre_books SET helpful_count = COALESCE(helpful_count,0) + 1 WHERE isbn=%s" if USE_PG else "UPDATE genre_books SET helpful_count = COALESCE(helpful_count,0) + 1 WHERE isbn=?", (isbn,))
    con.commit()
    row = fetchone(con, "SELECT helpful_count FROM genre_books WHERE isbn=%s" if USE_PG else "SELECT helpful_count FROM genre_books WHERE isbn=?", (isbn,))
    con.close()
    return jsonify({"helpful_count": row["helpful_count"] if row else 1})


@app.route("/api/rate", methods=["POST"])
@rate_limit(limit=10, window=60)
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
    rows = fetchall(con, "SELECT id, title, body, category, image_url, event_date, created_at FROM announcements ORDER BY id DESC")
    con.close()
    def parse_images(raw):
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else [v]
        except Exception:
            return [raw] if raw else []
    return jsonify([{**r, "images": parse_images(r.get("image_url")), "event_date": r.get("event_date") or "", "created_at": str(r["created_at"])[:16]} for r in rows])


@app.route("/api/announcements", methods=["POST"])
def api_post_announcement():
    body = request.get_json()
    pw = body.get("password")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    title = body.get("title", "").strip()
    text = body.get("body", "").strip()
    if not title or not text:
        return jsonify({"error": "invalid"}), 400
    con = get_con()
    images = body.get("images", [])
    if not images and body.get("image_url","").strip():
        images = [body.get("image_url","").strip()]
    event_date = body.get("event_date", "").strip()
    execute(con, "INSERT INTO announcements (title, body, category, image_url, event_date) VALUES (?,?,?,?,?)",
        (title, text, body.get("category","お知らせ"), json.dumps(images, ensure_ascii=False), event_date))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/announcements/<int:ann_id>", methods=["PATCH"])
def api_update_announcement(ann_id):
    body = request.get_json()
    pw = body.get("password")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    images = body.get("images", [])
    if not images and body.get("image_url","").strip():
        images = [body.get("image_url","").strip()]
    event_date = body.get("event_date", "").strip()
    execute(con, "UPDATE announcements SET title=?, body=?, category=?, image_url=?, event_date=? WHERE id=?",
        (body.get("title","").strip(), body.get("body","").strip(),
         body.get("category","お知らせ"), json.dumps(images, ensure_ascii=False), event_date, ann_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    body = request.get_json()
    pw = body.get("password")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM announcements WHERE id=?", (ann_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Book Requests ---
@app.route("/api/requests")
def api_requests():
    con = get_con()
    rows = fetchall(con, "SELECT id,title,author,reason,room,status,votes,created_at,type,reply FROM book_requests ORDER BY votes DESC, id DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10], "type": r.get("type") or "request", "reply": r.get("reply") or ""} for r in rows])

@app.route("/api/requests/admin")
def api_requests_admin():
    pw = request.headers.get("X-Password", "") or request.args.get("password", "")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    rows = fetchall(con, "SELECT id,title,author,reason,room,status,note,votes,created_at,type,reply FROM book_requests ORDER BY votes DESC, id DESC")
    con.close()
    return jsonify([{**r, "created_at": str(r["created_at"])[:10], "type": r.get("type") or "request", "reply": r.get("reply") or "", "note": r.get("note") or ""} for r in rows])


@app.route("/api/requests", methods=["POST"])
@rate_limit(limit=5, window=60)
def api_post_request():
    body = request.get_json()
    title = body.get("title", "").strip()
    req_type = body.get("type", "request")
    default_status = "fb_received" if req_type == "feedback" else "pending"
    if not title:
        return jsonify({"error": "title required"}), 400
    con = get_con()
    execute(con, "INSERT INTO book_requests (title,author,reason,room,type,status) VALUES (?,?,?,?,?,?)",
        (title, body.get("author","").strip(), body.get("reason","").strip(), body.get("room","").strip(), req_type, default_status))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/requests/<int:req_id>/vote", methods=["POST"])
@rate_limit(limit=10, window=60)
def api_vote_request(req_id):
    con = get_con()
    execute(con, "UPDATE book_requests SET votes = COALESCE(votes,0) + 1 WHERE id=?", (req_id,))
    con.commit()
    row = fetchone(con, "SELECT votes FROM book_requests WHERE id=?", (req_id,))
    con.close()
    return jsonify({"ok": True, "votes": row["votes"] if row else 0})

@app.route("/api/requests/<int:req_id>", methods=["PATCH"])
def api_update_request(req_id):
    body = request.get_json()
    pw = body.get("password")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    if "status" in body:
        execute(con, "UPDATE book_requests SET status=? WHERE id=?", (body["status"], req_id))
    if "note" in body:
        execute(con, "UPDATE book_requests SET note=? WHERE id=?", (body["note"], req_id))
    if "reply" in body:
        execute(con, "UPDATE book_requests SET reply=? WHERE id=?", (body["reply"], req_id))
    con.commit(); con.close()
    return jsonify({"ok": True})


@app.route("/api/requests/<int:req_id>", methods=["DELETE"])
def api_delete_request(req_id):
    body = request.get_json()
    pw = body.get("password")
    if pw != get_admin_password() and pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM book_requests WHERE id=?", (req_id,))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Staff Chat ---
@app.route("/api/staff_chat", methods=["GET"])
def api_staff_chat_get():
    pw = request.args.get("password", "")
    if pw != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    # 2年以上前のメッセージを自動削除
    if USE_PG:
        execute(con, "DELETE FROM staff_chat WHERE created_at < NOW() - INTERVAL '2 years'")
    else:
        execute(con, "DELETE FROM staff_chat WHERE created_at < datetime('now','-2 years','localtime')")
    con.commit()
    rows = fetchall(con, "SELECT id, sender, message, image_data, created_at FROM staff_chat ORDER BY created_at DESC LIMIT 100")
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/staff_chat", methods=["POST"])
def api_staff_chat_post():
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    sender = (body.get("sender") or "匿名").strip()
    message = (body.get("message") or "").strip()
    image_data = (body.get("image_data") or "").strip()
    if not message and not image_data:
        return jsonify({"error": "message or image required"}), 400
    con = get_con()
    execute(con, "INSERT INTO staff_chat (sender, message, image_data) VALUES (?, ?, ?)", (sender, message, image_data))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/staff_chat/<int:msg_id>", methods=["DELETE"])
def api_staff_chat_delete(msg_id):
    body = request.get_json()
    if body.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    execute(con, "DELETE FROM staff_chat WHERE id=?", (msg_id,))
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
    user = fetchone(con, "SELECT room, pin, favorites, reading_log, library_card_url, library_card_image FROM user_accounts WHERE room=?", (room,))
    if user is None:
        execute(con, "INSERT INTO user_accounts (room, pin) VALUES (?,?)", (room, pin))
        con.commit(); con.close()
        return jsonify({"ok": True, "is_new": True, "favorites": [], "reading_log": {}, "library_card_url": "", "library_card_image": ""})
    if user["pin"] != pin:
        con.close()
        return jsonify({"error": "PINが違います"}), 401
    con.close()
    return jsonify({
        "ok": True, "is_new": False,
        "favorites": json.loads(user["favorites"] or "[]"),
        "reading_log": json.loads(user["reading_log"] or "{}"),
        "library_card_url": user.get("library_card_url") or "",
        "library_card_image": user.get("library_card_image") or ""
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
    card_url = (body.get("library_card_url") or "")[:2000]
    card_img = body.get("library_card_image") or ""
    if USE_PG:
        execute(con, "UPDATE user_accounts SET favorites=?, reading_log=?, library_card_url=?, library_card_image=?, updated_at=NOW() WHERE room=?",
                (favs, rlog, card_url, card_img, room))
    else:
        execute(con, "UPDATE user_accounts SET favorites=?, reading_log=?, library_card_url=?, library_card_image=?, updated_at=datetime('now','localtime') WHERE room=?",
                (favs, rlog, card_url, card_img, room))
    con.commit(); con.close()
    return jsonify({"ok": True})


# --- Password change ---
@app.route("/api/admin/db-size")
def api_db_size():
    if request.args.get("password") != get_board_password():
        return jsonify({"error": "unauthorized"}), 401
    con = get_con()
    try:
        if USE_PG:
            size_row = fetchone(con, "SELECT pg_database_size(current_database()) AS bytes")
            total_bytes = size_row["bytes"]
            rows = fetchall(con, """
                SELECT relname AS name,
                       pg_total_relation_size(relid) AS bytes
                FROM pg_catalog.pg_statio_user_tables
                ORDER BY bytes DESC
            """)
            tables = [{"name": r["name"], "mb": round(r["bytes"]/1024/1024, 2)} for r in rows]
        else:
            import os as _os
            total_bytes = _os.path.getsize("data.db")
            tables = []
        con.close()
        limit_bytes = 512 * 1024 * 1024
        return jsonify({
            "total_mb": round(total_bytes / 1024 / 1024, 2),
            "limit_mb": 512,
            "percent": round(total_bytes / limit_bytes * 100, 1),
            "tables": tables
        })
    except Exception as e:
        con.close()
        return jsonify({"error": str(e)}), 500


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

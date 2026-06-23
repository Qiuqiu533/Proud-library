from __future__ import annotations
import threading
import logging
import requests

logger = logging.getLogger(__name__)

from database import get_con, execute, fetchone, fetchall, USE_PG
from config import GENRE_MAP, OPENBD_API
from seeds import _AWARDS_SEED, _AWARD_BOOKS_SEED
from services.utils import _hash_password, _ndc_to_genre, _keyword_genre
from services.awards import _sync_awards_from_master, _insert_genre_books, _normalize_pubdate
from config import get_board_password


_REQUIRED_TABLES = [
    "book_requests", "issues", "announcements", "genre_books",
    "new_arrivals", "lib_schedule", "ratings", "user_accounts",
    "admin_users", "settings", "staff_chat", "calendar_events",
    "availability_cache", "password_reset_tokens",
]


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
            CREATE TABLE IF NOT EXISTS collections (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                emoji TEXT DEFAULT '📚',
                isbns TEXT DEFAULT '[]',
                is_active BOOLEAN DEFAULT TRUE,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_accounts (
                room TEXT PRIMARY KEY,
                pin TEXT NOT NULL,
                email TEXT DEFAULT '',
                password_hash TEXT DEFAULT '',
                password_salt TEXT DEFAULT '',
                favorites TEXT DEFAULT '[]',
                reading_log TEXT DEFAULT '{}',
                library_card_url TEXT DEFAULT '',
                library_card_image TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token TEXT PRIMARY KEY,
                room TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS award_books (
                id SERIAL PRIMARY KEY,
                award TEXT NOT NULL,
                award_no INTEGER,
                award_year INTEGER,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                isbn13 TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                status TEXT DEFAULT '確認済',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT NOW()
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
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                emoji TEXT DEFAULT '📚',
                isbns TEXT DEFAULT '[]',
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_accounts (
                room TEXT PRIMARY KEY,
                pin TEXT NOT NULL,
                email TEXT DEFAULT '',
                password_hash TEXT DEFAULT '',
                password_salt TEXT DEFAULT '',
                favorites TEXT DEFAULT '[]',
                reading_log TEXT DEFAULT '{}',
                library_card_url TEXT DEFAULT '',
                library_card_image TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token TEXT PRIMARY KEY,
                room TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS genre_books (
                isbn TEXT PRIMARY KEY,
                genre TEXT DEFAULT '',
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                format TEXT DEFAULT '',
                awards TEXT DEFAULT '[]'
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.commit()
    con.close()


# ── マイグレーション管理ヘルパー ──────────────────────────────────────────────
def _migration_done(name: str) -> bool:  # noqa: D103
    """applied_migrations テーブルで適用済みか確認する。"""
    con = get_con()
    try:
        # applied_migrationsが存在しない場合（旧環境）はsettingsフォールバック
        try:
            row = fetchone(con, "SELECT name FROM applied_migrations WHERE name=?", (name,))
            return row is not None
        except Exception:
            return False
    finally:
        con.close()


def _mark_migration_done(name: str):
    """applied_migrations テーブルに適用済みとして記録する。"""
    con = get_con()
    try:
        if USE_PG:
            execute(con, "INSERT INTO applied_migrations(name) VALUES(%s) ON CONFLICT DO NOTHING", (name,))
        else:
            execute(con, "INSERT OR IGNORE INTO applied_migrations(name) VALUES(?)", (name,))
        con.commit()
    finally:
        con.close()


def _migrate_admin_users():
    """admin_usersテーブルを追加し、マスターアカウントがなければ初期作成する"""
    try:
        con = get_con()
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            con.commit()
            row = fetchone(con, "SELECT id FROM admin_users WHERE role='master' LIMIT 1")
            if not row:
                init_pw = get_board_password()
                if not init_pw:
                    raise RuntimeError("BOARD_PASSWORD 環境変数が未設定のため管理者初期化できません")
                h, s = _hash_password(init_pw)
                execute(con, "INSERT INTO admin_users (code, name, password_hash, salt, role) VALUES (?,?,?,?,?)",
                        ("A000", "秋山", h, s, "master"))
                con.commit()
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            con.commit()
            row = fetchone(con, "SELECT id FROM admin_users WHERE role='master' LIMIT 1")
            if not row:
                init_pw = get_board_password()
                if not init_pw:
                    raise RuntimeError("BOARD_PASSWORD 環境変数が未設定のため管理者初期化できません")
                h, s = _hash_password(init_pw)
                execute(con, "INSERT INTO admin_users (code, name, password_hash, salt, role) VALUES (?,?,?,?,?)",
                        ("A000", "秋山", h, s, "master"))
                con.commit()
        con.close()
    except Exception as e:
        logger.error(f"admin_users migration error: %s", e)


def _migrate_add_card_columns():
    """user_accounts に library_card_url/image カラム、genre_books に title_yomi/pubdate カラムを追加"""
    try:
        con = get_con()
        if USE_PG:
            for col in ("library_card_url", "library_card_image"):
                try:
                    con.cursor().execute(f"ALTER TABLE user_accounts ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    con.rollback()
            for col in ("title_yomi", "pubdate"):
                try:
                    con.cursor().execute(f"ALTER TABLE genre_books ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    con.rollback()
        else:
            for col in ("library_card_url", "library_card_image"):
                try:
                    con.execute(f"ALTER TABLE user_accounts ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    pass
            for col in ("title_yomi", "pubdate"):
                try:
                    con.execute(f"ALTER TABLE genre_books ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    pass
        con.close()
    except Exception as e:
        logger.error(f"card column migration error: %s", e)


def _migrate_add_user_auth_columns():
    """user_accounts に email/password_hash/password_salt カラムを追加"""
    try:
        con = get_con()
        if USE_PG:
            for col, default in [("email", "''"), ("password_hash", "''"), ("password_salt", "''")]:
                try:
                    con.cursor().execute(f"ALTER TABLE user_accounts ADD COLUMN {col} TEXT DEFAULT {default}")
                    con.commit()
                except Exception:
                    con.rollback()
            try:
                con.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS password_reset_tokens (
                        token TEXT PRIMARY KEY,
                        room TEXT NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        used BOOLEAN DEFAULT FALSE
                    )
                """)
                con.commit()
            except Exception:
                con.rollback()
        else:
            for col in ("email", "password_hash", "password_salt"):
                try:
                    con.execute(f"ALTER TABLE user_accounts ADD COLUMN {col} TEXT DEFAULT ''")
                    con.commit()
                except Exception:
                    pass
            try:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS password_reset_tokens (
                        token TEXT PRIMARY KEY,
                        room TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        used INTEGER DEFAULT 0
                    )
                """)
                con.commit()
            except Exception:
                pass
        con.close()
    except Exception as e:
        logger.error(f"user auth column migration error: %s", e)


def _migrate_ndc_genres():
    """OpenBD NDCコード＋キーワードでジャンル未分類の本を自動分類（改訂版で再実行）"""
    CURRENT_VERSION = "v3"
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='ndc_classify_done'")
        if done and done["value"] == CURRENT_VERSION:
            con.close()
            return
        rows = fetchall(con, "SELECT isbn, title, author FROM genre_books")
        con.close()
        if not rows:
            return
        kw_updated = 0
        con_kw = get_con()
        for r in rows:
            genre = _keyword_genre(r["title"] or "", r["author"] or "")
            if genre:
                execute(con_kw, "UPDATE genre_books SET genre=? WHERE isbn=? AND (genre='' OR genre IS NULL OR genre='その他')", (genre, r["isbn"]))
                kw_updated += 1
        con_kw.commit(); con_kw.close()

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
                        title_details = item.get("onix", {}).get("DescriptiveDetail", {}).get("TitleDetail", [])
                        yomi = ""
                        for td in title_details:
                            for te in td.get("TitleElement", []):
                                if te.get("TitleElementLevel") == "01":
                                    subtitle = te.get("Subtitle", {}).get("content", "") or te.get("Subtitle", "")
                                    if subtitle and any("぀" <= c <= "ヿ" for c in subtitle):
                                        yomi = subtitle
                                        break
                            if yomi:
                                break
                        if yomi and isbn:
                            execute(con3, "UPDATE genre_books SET title_yomi=? WHERE isbn=?", (yomi, isbn))
                    except Exception:
                        pass
                con3.commit(); con3.close()
            except Exception as e:
                logger.error(f"NDC batch error: %s", e)

        con4 = get_con()
        if USE_PG:
            execute(con4, "INSERT INTO settings(key,value) VALUES('ndc_classify_done',?) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (CURRENT_VERSION,))
        else:
            execute(con4, "INSERT OR REPLACE INTO settings(key,value) VALUES('ndc_classify_done',?)", (CURRENT_VERSION,))
        con4.commit(); con4.close()
        logger.info(f"NDC genre classification v2: keyword={kw_updated}, ndc={ndc_updated} books updated")
    except Exception as e:
        logger.error(f"NDC classify error: %s", e)


def _migrate_title_yomi():
    """title_yomiが空の本にpykakasiで読み仮名を一括生成する（100件ずつバッチ）"""
    try:
        con = get_con()
        flag = fetchone(con, "SELECT value FROM settings WHERE key='title_yomi_done'")
        con.close()
        if flag and flag["value"] == "1":
            return
        import pykakasi
        kks = pykakasi.kakasi()
        con = get_con()
        rows = fetchall(con, "SELECT isbn, title FROM genre_books WHERE title_yomi IS NULL OR title_yomi = ''")
        con.close()
        if not rows:
            logger.info("[yomi] 全件登録済み")
            return
        logger.info(f"[yomi] {len(rows)}件のよみがなを生成します")
        updated = 0
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            con = get_con()
            for r in batch:
                try:
                    result = kks.convert(r["title"])
                    yomi = "".join(item["hira"] for item in result)
                    if yomi:
                        execute(con, "UPDATE genre_books SET title_yomi=? WHERE isbn=?", (yomi, r["isbn"]))
                        updated += 1
                except Exception:
                    pass
            con.commit()
            con.close()
            logger.info(f"[yomi] {min(i + batch_size, len(rows))}/{len(rows)}件処理中...")
        con = get_con()
        if USE_PG:
            execute(con, "INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", ("title_yomi_done", "1"))
        else:
            execute(con, "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", ("title_yomi_done", "1"))
        con.commit()
        con.close()
        logger.info(f"[yomi] 完了: {updated}件登録しました")
    except ImportError:
        logger.info("[yomi] pykakasi未インストール")
    except Exception as e:
        logger.error(f"[yomi] migrate error: %s", e)


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
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_threads (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            try:
                cur.execute("ALTER TABLE staff_chat ADD COLUMN thread_id INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE")
            except Exception:
                con.rollback()
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS chat_threads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            try:
                con.execute("ALTER TABLE staff_chat ADD COLUMN thread_id INTEGER")
            except Exception:
                pass
        con.commit()
        con.close()
    except Exception as e:
        logger.error(f"migrate staff_chat error: %s", e)


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
        logger.error(f"migrate votes error: %s", e)


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
        logger.error(f"migrate type/reply error: %s", e)


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
        logger.error(f"migrate lib_schedule error: %s", e)


def _migrate_genre_map_to_db():
    """genre_map.json が存在し DB が空なら一度だけ移行する"""
    try:
        con = get_con()
        row = fetchone(con, "SELECT COUNT(*) as cnt FROM genre_books")
        if row and row["cnt"] > 0:
            con.close()
            return
        if not GENRE_MAP:
            con.close()
            return
        _insert_genre_books(con, GENRE_MAP)
        con.commit()
        con.close()
        logger.info(f"genre_map.json → DB 移行完了")
    except Exception as e:
        logger.error(f"genre migrate error: %s", e)


def _migrate_seed_awards_master():
    """awards_masterにシードデータを投入し、genre_booksの受賞バッジを再マッチング"""
    if not USE_PG:
        return
    # applied_migrationsで管理（旧settingsフラグとの後方互換も保持）
    if _migration_done("awards_seed_v4"):
        return
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='awards_seed_done'")
        if done and done.get("value") == "v4":
            con.close()
            _mark_migration_done("awards_seed_v4")
            return
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS awards_master (
                id SERIAL PRIMARY KEY,
                award TEXT NOT NULL,
                year INTEGER,
                rank INTEGER,
                type TEXT DEFAULT '受賞',
                title TEXT NOT NULL,
                author TEXT DEFAULT ''
            )
        """)
        cur.execute("TRUNCATE awards_master RESTART IDENTITY")
        cur.executemany(
            "INSERT INTO awards_master (award, year, rank, type, title, author) VALUES (%s,%s,%s,%s,%s,%s)",
            _AWARDS_SEED
        )
        cur.execute("DELETE FROM settings WHERE key IN ('awards_resync_done','awards_resync_done_v2','awards_resync_done_v3','awards_resync_done_v4')")
        cur.execute("""
            INSERT INTO settings(key,value) VALUES('awards_seed_done','v4')
            ON CONFLICT(key) DO UPDATE SET value='v2'
        """)
        con.commit()
        con.close()
        _mark_migration_done("awards_seed_v4")
        logger.info(f"[awards_seed] {len(_AWARDS_SEED)}件登録完了、全件再マッチング開始")
        _migrate_resync_awards_v2()
        _migrate_resync_awards_v3()
        _migrate_resync_awards_v4()
    except Exception as e:
        logger.error(f"[awards_seed] error: %s", e)


def _migrate_resync_awards():
    """awards=NULLまたは[]の本を対象にawards_masterと再マッチング"""
    if not USE_PG:
        return
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='awards_resync_done'")
        if done and done.get("value") == "v1":
            con.close()
            return
        rows = fetchall(con, "SELECT isbn, title, author FROM genre_books WHERE awards IS NULL OR awards = '[]'::jsonb")
        updated = 0
        for r in rows:
            _sync_awards_from_master(con, r["isbn"], r["title"], r["author"])
            updated += 1
        if USE_PG:
            execute(con, "INSERT INTO settings(key,value) VALUES('awards_resync_done','v1') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
        con.commit()
        con.close()
        logger.info(f"awards resync: {updated} books re-matched")
    except Exception as e:
        logger.error(f"awards resync error: %s", e)


def _migrate_resync_awards_v2():
    """全冊を対象にawards_masterと再マッチング"""
    if not USE_PG:
        return
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='awards_resync_done_v2'")
        if done and done.get("value") == "v1":
            con.close()
            return
        rows = fetchall(con, "SELECT isbn, title, author FROM genre_books")
        con.close()
        updated = 0
        for r in rows:
            con = get_con()
            _sync_awards_from_master(con, r["isbn"], r["title"], r["author"])
            con.commit()
            con.close()
            updated += 1
        con = get_con()
        execute(con, "INSERT INTO settings(key,value) VALUES('awards_resync_done_v2','v1') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
        con.commit()
        con.close()
        logger.info(f"awards resync v2: {updated}冊全件マッチング完了")
    except Exception as e:
        logger.error(f"awards resync v2 error: %s", e)


def _migrate_resync_awards_v3():
    """直木賞シードデータ修正後の全件再マッチング (v3)"""
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='awards_resync_done_v3'")
        if done and done.get("value") == "v1":
            con.close()
            return
        rows = fetchall(con, "SELECT isbn, title, author FROM genre_books")
        con.close()
        updated = 0
        for r in rows:
            con = get_con()
            _sync_awards_from_master(con, r["isbn"], r["title"], r["author"])
            con.commit()
            con.close()
            updated += 1
        con = get_con()
        execute(con, "INSERT INTO settings(key,value) VALUES('awards_resync_done_v3','v1') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
        con.commit()
        con.close()
        logger.info(f"awards resync v3: {updated}冊全件マッチング完了")
    except Exception as e:
        logger.error(f"awards resync v3 error: %s", e)


def _migrate_resync_awards_v4():
    """江戸川乱歩賞追加後の全件再マッチング (v4)"""
    try:
        con = get_con()
        done = fetchone(con, "SELECT value FROM settings WHERE key='awards_resync_done_v4'")
        if done and done.get("value") == "v1":
            con.close()
            return
        rows = fetchall(con, "SELECT isbn, title, author FROM genre_books")
        con.close()
        updated = 0
        for r in rows:
            con = get_con()
            _sync_awards_from_master(con, r["isbn"], r["title"], r["author"])
            con.commit()
            con.close()
            updated += 1
        con = get_con()
        execute(con, "INSERT INTO settings(key,value) VALUES('awards_resync_done_v4','v1') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
        con.commit()
        con.close()
        logger.info(f"awards resync v4: {updated}冊全件マッチング完了")
    except Exception as e:
        logger.error(f"awards resync v4 error: %s", e)


def _migrate_seed_award_books():
    """award_booksテーブルに受賞作シードデータを投入する"""
    if not USE_PG:
        return
    try:
        con = get_con()
        flag = fetchone(con, "SELECT value FROM settings WHERE key='award_books_seed_done'")
        if flag and flag.get("value") == "v4":
            con.close()
            return
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS award_books (
                id SERIAL PRIMARY KEY,
                award TEXT NOT NULL,
                award_no INTEGER,
                award_year INTEGER,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                isbn13 TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                status TEXT DEFAULT '確認済',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("DELETE FROM award_books")
        cur.executemany(
            "INSERT INTO award_books (award, award_no, award_year, title, author, status) VALUES (%s,%s,%s,%s,%s,%s)",
            _AWARD_BOOKS_SEED
        )
        cur.execute("INSERT INTO settings(key,value) VALUES('award_books_seed_done','v4') ON CONFLICT(key) DO UPDATE SET value='v4'")
        con.commit()
        con.close()
        logger.info(f"[award_books_seed] {len(_AWARD_BOOKS_SEED)}件投入完了")
    except Exception as e:
        logger.error(f"[award_books_seed] error: %s", e)


def _migrate_pubdate_openbd():
    """Phase1: OpenBD一括取得でgenre_books.pubdateを埋める"""
    if not USE_PG:
        return
    try:
        con = get_con()
        flag = fetchone(con, "SELECT value FROM settings WHERE key='pubdate_openbd_done'")
        if flag and flag.get("value") == "v1":
            con.close()
            return
        rows = fetchall(con, "SELECT isbn FROM genre_books WHERE pubdate IS NULL OR pubdate = ''")
        con.close()
        if not rows:
            return
        isbns = [r["isbn"] for r in rows]
        logger.info(f"[pubdate_openbd] {len(isbns)}冊のpubdateをOpenBDから取得します")
        updated = 0
        for i in range(0, len(isbns), 1000):
            batch = isbns[i:i + 1000]
            try:
                resp = requests.get(OPENBD_API, params={"isbn": ",".join(batch)}, timeout=30)
                con = get_con()
                for item in resp.json():
                    if not item:
                        continue
                    summary = item.get("summary", {})
                    isbn = summary.get("isbn", "")
                    norm = _normalize_pubdate(summary.get("pubdate", "") or "")
                    if isbn and norm:
                        execute(con, "UPDATE genre_books SET pubdate=? WHERE isbn=? AND (pubdate IS NULL OR pubdate='')", (norm, isbn))
                        updated += 1
                con.commit()
                con.close()
            except Exception as e:
                logger.error(f"[pubdate_openbd] batch error: %s", e)
        logger.info(f"[pubdate_openbd] {updated}冊更新完了")
        con = get_con()
        execute(con, "INSERT INTO settings(key,value) VALUES('pubdate_openbd_done','v1') ON CONFLICT(key) DO UPDATE SET value='v1'")
        con.commit()
        con.close()
        threading.Thread(target=_migrate_pubdate_librarylife, daemon=True).start()
    except Exception as e:
        logger.error(f"[pubdate_openbd] error: %s", e)


def _migrate_pubdate_librarylife():
    """Phase2: OpenBDで取得できなかった本をlibrarylife.netから1冊ずつ補完"""
    if not USE_PG:
        return
    try:
        con = get_con()
        flag = fetchone(con, "SELECT value FROM settings WHERE key='pubdate_ll_done'")
        if flag and flag.get("value") == "v1":
            con.close()
            return
        rows = fetchall(con, "SELECT isbn FROM genre_books WHERE pubdate IS NULL OR pubdate = ''")
        con.close()
        if not rows:
            return
        import time
        from services.books import fetch_book_detail
        logger.info(f"[pubdate_ll] {len(rows)}冊をlibrarylifeから補完します")
        updated = 0
        for r in rows:
            try:
                detail = fetch_book_detail(r["isbn"])
                norm = _normalize_pubdate(detail.get("pubdate", "") or "")
                if norm:
                    con = get_con()
                    execute(con, "UPDATE genre_books SET pubdate=? WHERE isbn=?", (norm, r["isbn"]))
                    con.commit()
                    con.close()
                    updated += 1
                time.sleep(1)
            except Exception:
                pass
        logger.info(f"[pubdate_ll] {updated}冊補完完了")
        con = get_con()
        execute(con, "INSERT INTO settings(key,value) VALUES('pubdate_ll_done','v1') ON CONFLICT(key) DO UPDATE SET value='v1'")
        con.commit()
        con.close()
    except Exception as e:
        logger.error(f"[pubdate_ll] error: %s", e)


def _verify_tables():
    """起動時にテーブル名を検証してミスを早期検出する"""
    try:
        con = get_con()
        if USE_PG:
            rows = fetchall(con, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
            existing = {r["tablename"] for r in rows}
        else:
            rows = fetchall(con, "SELECT name FROM sqlite_master WHERE type='table'")
            existing = {r["name"] for r in rows}
        con.close()
        missing = [t for t in _REQUIRED_TABLES if t not in existing]
        if missing:
            logger.warning(f" テーブルが見つかりません: {missing}")
        else:
            logger.info(f"[OK] 全テーブル確認済み ({len(_REQUIRED_TABLES)}件)")
    except Exception as e:
        logger.error(f"table verify error: %s", e)


def _migrate_ratings_user_votes():
    """ratings テーブルに user_votes カラムを追加（部屋別スコア管理・重複投票防止）。"""
    if _migration_done("ratings_user_votes_v1"):
        return
    if not USE_PG:
        _mark_migration_done("ratings_user_votes_v1")
        return
    con = get_con()
    try:
        cur = con.cursor()
        cur.execute("ALTER TABLE ratings ADD COLUMN IF NOT EXISTS user_votes TEXT DEFAULT '{}'")
        con.commit()
        _mark_migration_done("ratings_user_votes_v1")
        logger.info("[migration] ratings.user_votes カラム追加完了")
    except Exception as e:
        logger.error(f"[migration] ratings_user_votes error: %s", e)
    finally:
        con.close()


def _migrate_genre_books_awards():
    """genre_books テーブルに awards カラムを追加（SQLite/PG共通）。"""
    if _migration_done("genre_books_awards_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE genre_books ADD COLUMN IF NOT EXISTS awards JSONB DEFAULT '[]'::jsonb")
        else:
            cols = [row[1] for row in con.execute("PRAGMA table_info(genre_books)")]
            if "awards" not in cols:
                con.execute("ALTER TABLE genre_books ADD COLUMN awards TEXT DEFAULT '[]'")
        con.commit()
        _mark_migration_done("genre_books_awards_v1")
        logger.info("[migration] genre_books.awards カラム追加完了")
    except Exception as e:
        logger.error(f"[migration] genre_books_awards error: %s", e)
    finally:
        con.close()


def _migrate_wish_list():
    """wish_list テーブルを追加（読みたい本ウィッシュリスト）。"""
    if _migration_done("wish_list_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wish_list (
                    id SERIAL PRIMARY KEY,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(room, isbn)
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS wish_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(room, isbn)
                )
            """)
        con.commit()
        _mark_migration_done("wish_list_v1")
        logger.info("[migration] wish_list テーブル追加完了")
    except Exception as e:
        logger.error(f"[migration] wish_list error: %s", e)
    finally:
        con.close()


def _migrate_wish_list_notify():
    """wish_list に通知用カラム notify / notified_at を追加。"""
    if _migration_done("wish_list_notify_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            try:
                cur.execute("ALTER TABLE wish_list ADD COLUMN notify BOOLEAN NOT NULL DEFAULT TRUE")
                con.commit()
            except Exception:
                con.rollback()
            try:
                cur.execute("ALTER TABLE wish_list ADD COLUMN notified_at TIMESTAMPTZ")
                con.commit()
            except Exception:
                con.rollback()
        else:
            try:
                con.execute("ALTER TABLE wish_list ADD COLUMN notify INTEGER NOT NULL DEFAULT 1")
                con.commit()
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE wish_list ADD COLUMN notified_at TIMESTAMP")
                con.commit()
            except Exception:
                pass
        _mark_migration_done("wish_list_notify_v1")
        logger.info("[migration] wish_list notify カラム追加完了")
    except Exception as e:
        logger.error("[migration] wish_list_notify error: %s", e)
    finally:
        con.close()


def _migrate_invite_codes():
    """invite_codes テーブルを追加（招待コードによる登録制限）。"""
    if _migration_done("invite_codes_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS invite_codes (
                    id SERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    note TEXT DEFAULT '',
                    used_room TEXT DEFAULT '',
                    used_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS invite_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    note TEXT DEFAULT '',
                    used_room TEXT DEFAULT '',
                    used_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        con.commit()
        _mark_migration_done("invite_codes_v1")
        logger.info("[migration] invite_codes テーブル追加完了")
    except Exception as e:
        logger.error("[migration] invite_codes error: %s", e)
    finally:
        con.close()


def _migrate_audit_log():
    """audit_log テーブルを追加（管理者操作ログ）。"""
    if _migration_done("audit_log_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    action TEXT NOT NULL,
                    target TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    ip TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    target TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    ip TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        con.commit()
        _mark_migration_done("audit_log_v1")
        logger.info("[migration] audit_log テーブル追加完了")
    except Exception as e:
        logger.error("[migration] audit_log error: %s", e)
    finally:
        con.close()


def _migrate_events():
    """events / event_entries テーブルを追加（イベント申込機能）。"""
    if _migration_done("events_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    event_date TEXT NOT NULL,
                    event_time TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    capacity INTEGER DEFAULT 0,
                    entry_deadline TEXT DEFAULT '',
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_entries (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    room TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    is_waitlist BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(event_id, room)
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    event_date TEXT NOT NULL,
                    event_time TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    capacity INTEGER DEFAULT 0,
                    entry_deadline TEXT DEFAULT '',
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS event_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    room TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    is_waitlist INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(event_id, room)
                )
            """)
        con.commit()
        _mark_migration_done("events_v1")
        logger.info("[migration] events テーブル追加完了")
    except Exception as e:
        logger.error("[migration] events error: %s", e)
    finally:
        con.close()


def _run_all_migrations():
    """全マイグレーションをシングルスレッドで順次実行する（race condition防止）。"""
    steps = [
        _migrate_add_card_columns,
        _migrate_add_user_auth_columns,
        _migrate_admin_users,
        _migrate_genre_map_to_db,
        _migrate_add_votes_column,
        _migrate_add_type_reply_columns,
        _migrate_add_staff_chat,
        _migrate_lib_schedule,
        _migrate_seed_awards_master,   # シード投入
        _migrate_resync_awards_v2,     # 旧バージョン互換
        _migrate_resync_awards_v3,
        _migrate_resync_awards_v4,
        _migrate_seed_award_books,
        _migrate_title_yomi,
        _migrate_pubdate_openbd,       # 完了後に librarylife を内部で起動
        _migrate_ndc_genres,           # 重い処理は最後
        _migrate_ratings_user_votes,   # ratings.user_votes カラム追加
        _migrate_genre_books_awards,   # genre_books.awards カラム追加
        _migrate_wish_list,            # wish_list テーブル追加
        _migrate_wish_list_notify,     # 通知用カラム追加
        _migrate_invite_codes,         # 招待コードテーブル追加
        _migrate_audit_log,            # 管理者操作ログ
        _migrate_events,               # イベント申込テーブル
        _verify_tables,
    ]
    for step in steps:
        try:
            step()
        except Exception as e:
            logger.error(f"[migration error] {step.__name__}: %s", e)


def _ensure_db():
    try:
        init_db()
    except Exception as e:
        logger.error(f"DB init error: %s", e)
    threading.Thread(target=_run_all_migrations, daemon=True).start()
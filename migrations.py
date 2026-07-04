from __future__ import annotations
import threading
import logging
import requests
import psycopg2.errors

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
        except psycopg2.errors.DuplicateColumn:
            con.rollback()
        try:
            cur.execute("ALTER TABLE genre_books ADD COLUMN description TEXT DEFAULT ''")
            con.commit()
        except psycopg2.errors.DuplicateColumn:
            con.rollback()
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


def _migrate_reading_timeline():
    """reading_timeline テーブルを追加（読書タイムライン機能）。"""
    if _migration_done("reading_timeline_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reading_timeline (
                    id SERIAL PRIMARY KEY,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    cover TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    comment TEXT DEFAULT '',
                    nickname TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_created ON reading_timeline(created_at DESC)")
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS reading_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    cover TEXT DEFAULT '',
                    status TEXT NOT NULL,
                    comment TEXT DEFAULT '',
                    nickname TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        con.commit()
        _mark_migration_done("reading_timeline_v1")
        logger.info("[migration] reading_timeline テーブル追加完了")
    except Exception as e:
        logger.error("[migration] reading_timeline error: %s", e)
    finally:
        con.close()


def _migrate_newsletters():
    """newsletters テーブルを追加（図書館だより機能）。"""
    if _migration_done("newsletters_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS newsletters (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    sent_count INTEGER DEFAULT 0,
                    created_by TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS newsletters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    sent_count INTEGER DEFAULT 0,
                    created_by TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        con.commit()
        _mark_migration_done("newsletters_v1")
        logger.info("[migration] newsletters テーブル追加完了")
    except Exception as e:
        logger.error("[migration] newsletters error: %s", e)
    finally:
        con.close()


def _migrate_events_image():
    """events テーブルに image_data カラムを追加する。"""
    if _migration_done("events_image_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS image_data TEXT DEFAULT ''")
        else:
            try:
                con.execute("ALTER TABLE events ADD COLUMN image_data TEXT DEFAULT ''")
            except Exception:
                pass
        con.commit()
        _mark_migration_done("events_image_v1")
        logger.info("[migration] events.image_data カラム追加完了")
    except Exception as e:
        logger.error("[migration] events_image error: %s", e)
    finally:
        con.close()


_AWARD_ISBN_DATA = [
    ("このミス大賞",2025,"9784041111659","地雷グリコ"),("このミス大賞",2024,"9784163917680","可燃物"),("このミス大賞",2023,"9784065286661","爆弾"),("このミス大賞",2022,"9784065244005","黒牢城"),("このミス大賞",2021,"9784065203439","元彼の遺言状"),("このミス大賞",2020,"9784163910414","ノースライト"),("このミス大賞",2019,"9784065125601","それまでの明日"),("このミス大賞",2018,"9784062205726","屍人荘の殺人"),("このミス大賞",2017,"9784062202404","蜜蜂と遠雷"),("このミス大賞",2016,"9784062194860","王とサーカス"),("このミス大賞",2015,"9784062191234","満願"),("このミス大賞",2014,"9784163826104","去年の冬、きみと別れ"),("このミス大賞",2013,"9784062177924","64（ロクヨン）"),("このミス大賞",2012,"9784163801101","ジェノサイド"),("このミス大賞",2011,"9784062160568","悪の教典"),("このミス大賞",2010,"9784062764445","新参者"),
    ("本格ミステリ大賞",2025,"9784041149676","彼女が探偵でなければ"),("本格ミステリ大賞",2024,"9784041111659","地雷グリコ"),("本格ミステリ大賞",2023,"9784103535114","名探偵のいけにえ―人民教会殺人事件―"),("本格ミステリ大賞",2022,"9784488028459","黒牢城"),("本格ミステリ大賞",2022,"9784488025557","大鞠家殺人事件"),("本格ミステリ大賞",2021,"9784488028046","蝉かえる"),("本格ミステリ大賞",2020,"9784065174272","法廷遊戯"),("本格ミステリ大賞",2019,"9784062941198","火のないところに煙は"),("本格ミステリ大賞",2018,"9784488025557","屍人荘の殺人"),("本格ミステリ大賞",2017,"9784062202404","涙香迷宮"),("本格ミステリ大賞",2016,"9784488027483","死と砂時計"),("本格ミステリ大賞",2015,"9784062194860","さよなら神様"),("本格ミステリ大賞",2013,"9784488025366","密室蒐集家"),("本格ミステリ大賞",2012,"9784062171342","開かせていただき光栄です"),("本格ミステリ大賞",2011,"9784163297904","隻眼の少女"),("本格ミステリ大賞",2010,"9784061826519","水魑の如き沈むもの"),("本格ミステリ大賞",2010,"9784061826984","密室殺人ゲーム2.0"),
    ("推理作家協会賞",2025,"9784065375884","崑崙奴"),("推理作家協会賞",2024,"9784041111659","地雷グリコ"),("推理作家協会賞",2024,"9784396636562","不夜島"),("推理作家協会賞",2023,"9784041124628","夜の道標"),("推理作家協会賞",2023,"9784022518378","君のクイズ"),("推理作家協会賞",2022,"9784065264355","同志少女よ、敵を撃て"),("推理作家協会賞",2021,"9784041082836","スワン"),("推理作家協会賞",2020,"9784065148945","ノワールをまとう女"),("推理作家協会賞",2019,"9784062205726","屍人荘の殺人"),("推理作家協会賞",2018,"9784488025557","孤狼の血"),("推理作家協会賞",2017,"9784334911461","QJKJQ"),("推理作家協会賞",2016,"9784062194860","さよなら神様"),("推理作家協会賞",2015,"9784062189132","満願"),("推理作家協会賞",2014,"9784344021747","後悔と真実の色"),("推理作家協会賞",2013,"9784344022102","百年法"),("推理作家協会賞",2012,"9784048741835","ジェノサイド"),("推理作家協会賞",2011,"9784163297904","隻眼の少女"),("推理作家協会賞",2011,"9784488014513","折れた竜骨"),("推理作家協会賞",2010,"9784048740173","粘膜蜥蜴"),("推理作家協会賞",2010,"9784022506238","乱反射"),
    ("山本周五郎賞",2025,"9784344042599","女の国会"),("山本周五郎賞",2024,"9784041111659","地雷グリコ"),("山本周五郎賞",2023,"9784103528826","木挽町のあだ討ち"),("山本周五郎賞",2022,"9784065235249","黛家の兄弟"),("山本周五郎賞",2021,"9784041096031","テスカトリポカ"),("山本周五郎賞",2020,"9784103361539","ザ・ロイヤルファミリー"),("山本周五郎賞",2019,"9784334912796","平場の月"),("山本周五郎賞",2018,"9784152097941","ゲームの王国 上"),("山本周五郎賞",2017,"9784101800726","明るい夜に出かけて"),("山本周五郎賞",2016,"9784087716196","ユートピア"),("山本周五郎賞",2015,"9784163902921","ナイルパーチの女子会"),("山本周五郎賞",2014,"9784101287848","満願"),("山本周五郎賞",2013,"9784103970045","残穢"),("山本周五郎賞",2012,"9784103317512","楽園のカンヴァス"),("山本周五郎賞",2011,"9784103259225","ふがいない僕は空を見た"),("山本周五郎賞",2010,"9784344019317","後悔と真実の色"),("山本周五郎賞",2010,"9784087713614","光媒の花"),
    ("吉川英治文学賞",2025,"9784104346085","方舟を燃やす"),("吉川英治文学賞",2024,"9784022518880","悪逆"),("吉川英治文学賞",2023,"9784087718022","燕は戻ってこない"),("吉川英治文学賞",2022,"9784065222690","やさしい猫"),("吉川英治文学賞",2022,"9784041116609","遠巷説百物語"),("吉川英治文学賞",2021,"9784087717162","風よ あらしよ"),("吉川英治文学賞",2019,"9784103112315","鏡の背面"),("吉川英治文学賞",2018,"9784103314245","守教"),("吉川英治文学賞",2017,"9784163904512","大雪物語"),("吉川英治文学賞",2016,"9784163903164","東京零年"),("吉川英治文学賞",2015,"9784163817609","平蔵狩り"),("吉川英治文学賞",2014,"9784163820300","ホテルローヤル"),("吉川英治文学賞",2013,"9784106022369","国銅"),("吉川英治文学賞",2012,"9784163806809","恋歌"),("吉川英治文学賞",2011,"9784062166720","月と蟹"),("吉川英治文学賞",2010,"9784062157711","廃墟に乞う"),
    ("SF大賞",2024,"9784152103321","プロトコル・オブ・ヒューマニティ"),("SF大賞",2023,"9784575245752","残月記"),("SF大賞",2021,"9784592160274","大奥"),("SF大賞",2020,"9784152100511","星系出雲の兵站"),("SF大賞",2019,"9784152098702","自生の夢"),("SF大賞",2018,"9784152097460","BEATLESS"),("SF大賞",2015,"9784152095053","オービタル・クラウド"),("SF大賞",2014,"9784152094223","去年はいい年になるだろう"),("SF大賞",2013,"9784150310516","屍者の帝国"),("SF大賞",2012,"9784062176682","盤上の夜"),("SF大賞",2011,"9784062768573","機龍警察"),("SF大賞",2010,"9784048740791","ペンギン・ハイウェイ"),
    ("ホラー大賞",2025,"9784299067746","右園死児報告"),("ホラー大賞",2024,"9784299055361","をんごく"),("ホラー大賞",2023,"9784299045317","入居条件:隣に住んでる友人と必ず仲良くしてください"),("ホラー大賞",2022,"9784299029270","忌み地 怪談社奇聞録"),("ホラー大賞",2021,"9784299014139","事故物件怪談 恐い間取り"),("ホラー大賞",2018,"9784800277701","ぼぎわんが、来る"),("ホラー大賞",2017,"9784800265487","などらきの首"),
    ("本屋大賞",2025,"9784065350263","カフネ"),("本屋大賞",2024,"9784103549517","成瀬は天下を取りにいく"),("本屋大賞",2023,"9784065287675","汝、星のごとく"),("本屋大賞",2022,"9784152100641","同志少女よ、敵を撃て"),("本屋大賞",2021,"9784120052989","52ヘルツのクジラたち"),("本屋大賞",2020,"9784488028022","流浪の月"),("本屋大賞",2019,"9784163907957","そして、バトンは渡された"),("本屋大賞",2018,"9784591153321","かがみの孤城"),("本屋大賞",2017,"9784344030039","蜜蜂と遠雷"),("本屋大賞",2016,"9784163902945","羊と鋼の森"),("本屋大賞",2015,"9784041018880","鹿の王"),("本屋大賞",2014,"9784103068827","村上海賊の娘"),("本屋大賞",2013,"9784062175647","海賊とよばれた男"),("本屋大賞",2012,"9784334768805","舟を編む"),("本屋大賞",2011,"9784093862801","謎解きはディナーのあとで"),("本屋大賞",2010,"9784048740135","天地明察"),
    ("芥川賞",2025,"9784065397510","時の家"),("芥川賞",2025,"9784103561113","叫び"),("芥川賞",2024,"9784309032429","DTOPIA"),("芥川賞",2024,"9784022520357","ゲーテはすべてを言った"),("芥川賞",2024,"9784103555112","サンショウウオの四十九日"),("芥川賞",2024,"9784065350263","バリ山行"),("芥川賞",2023,"9784103555815","東京都同情塔"),("芥川賞",2023,"9784163917307","ハンチバック"),("芥川賞",2022,"9784065297209","この世の喜びよ"),("芥川賞",2022,"9784103541610","荒地の家族"),("芥川賞",2022,"9784065287675","おいしいごはんが食べられますように"),("芥川賞",2021,"9784065267424","ブラックボックス"),("芥川賞",2021,"9784065249895","貝に続く場所にて"),("芥川賞",2021,"9784163915419","彼岸花が咲く島"),("芥川賞",2020,"9784309029160","推し、燃ゆ"),("芥川賞",2020,"9784103533813","首里の馬"),("芥川賞",2020,"9784309028897","破局"),("芥川賞",2019,"9784087716721","背高泡立草"),("芥川賞",2019,"9784022516237","むらさきのスカートの女"),("芥川賞",2018,"9784065132500","ニムロッド"),("芥川賞",2018,"9784103521711","1R1分34秒"),("芥川賞",2017,"9784163907308","送り火"),("芥川賞",2017,"9784103514416","影裏"),("芥川賞",2016,"9784103510814","しんせかい"),("芥川賞",2016,"9784062201469","コンビニ人間"),("芥川賞",2015,"9784062198035","スクラップ・アンド・ビルド"),("芥川賞",2015,"9784163903409","火花"),("芥川賞",2014,"9784103355316","九年前の祈り"),("芥川賞",2014,"9784062191913","春の庭"),("芥川賞",2013,"9784062187046","穴"),("芥川賞",2013,"9784103317512","爪と目"),("芥川賞",2012,"9784103317512","abさんご"),("芥川賞",2012,"9784062177924","冥土めぐり"),("芥川賞",2011,"9784103317512","共喰い"),("芥川賞",2011,"9784103317512","道化師の蝶"),("芥川賞",2010,"9784103317512","きことわ"),("芥川賞",2010,"9784103317512","乙女の密告"),
    ("直木賞",2025,"9784488029227","カフェーの帰り道"),("直木賞",2024,"9784103362147","藍を継ぐ海"),("直木賞",2024,"9784334100933","ツミデミック"),("直木賞",2023,"9784103555815","ともぐい"),("直木賞",2023,"9784163917710","八月の御所グラウンド"),("直木賞",2023,"9784163917123","極楽征夷大将軍"),("直木賞",2023,"9784103528826","木挽町のあだ討ち"),("直木賞",2022,"9784087718015","地図と拳"),("直木賞",2022,"9784103341944","しろがねの葉"),("直木賞",2022,"9784163915419","夜に星を放つ"),("直木賞",2021,"9784087717667","塞王の楯"),("直木賞",2021,"9784041113936","黒牢城"),("直木賞",2021,"9784041096031","テスカトリポカ"),("直木賞",2021,"9784163913675","星落ちて、なお"),("直木賞",2020,"9784087717162","心淋し川"),("直木賞",2020,"9784163911886","少年と犬"),("直木賞",2019,"9784163910445","熱源"),("直木賞",2019,"9784163909883","渦 妹背山婦女庭訓 魂結び"),("直木賞",2018,"9784065128251","宝島"),("直木賞",2018,"9784163909548","銀河鉄道の父"),("直木賞",2017,"9784000612180","月の満ち欠け"),("直木賞",2016,"9784344030039","蜜蜂と遠雷"),("直木賞",2016,"9784163904772","海の見える理髪店"),("直木賞",2015,"9784163903768","つまをめとらば"),("直木賞",2015,"9784062196628","流"),("直木賞",2014,"9784093863921","サラバ！"),("直木賞",2014,"9784041011119","破門"),("直木賞",2013,"9784062187091","恋歌"),("直木賞",2013,"9784344024496","昭和の犬"),("直木賞",2012,"9784087714147","ホテルローヤル"),("直木賞",2012,"9784103330610","何者"),("直木賞",2012,"9784103319523","等伯"),("直木賞",2011,"9784163806809","鍵のない夢を見る"),("直木賞",2011,"9784396633820","蜩ノ記"),("直木賞",2010,"9784093862955","下町ロケット"),("直木賞",2010,"9784120041778","漂砂のうたう"),("直木賞",2010,"9784163297904","月と蟹"),("直木賞",2010,"9784163280803","小さいおうち"),
]


def _migrate_update_award_isbn():
    """受賞作テーブルのisbn13を一括更新（CSVデータ提供分）。"""
    if _migration_done("award_isbn_bulk_v1"):
        return
    if not USE_PG:
        return
    con = get_con()
    try:
        rows = fetchall(con, "SELECT id, award, award_year, title, isbn13 FROM award_books WHERE status='確認済'")
        updated = 0
        for (award, year, isbn, title) in _AWARD_ISBN_DATA:
            for r in rows:
                if r["award"] == award and r["award_year"] == year and r["title"].strip() == title.strip():
                    if r["isbn13"] != isbn:
                        execute(con, "UPDATE award_books SET isbn13=%s WHERE id=%s", (isbn, r["id"]))
                        updated += 1
        con.commit()
        _mark_migration_done("award_isbn_bulk_v1")
        logger.info("[migration] 受賞作ISBN一括更新完了: %d件", updated)
    except Exception as e:
        logger.error("[migration] award_isbn_bulk error: %s", e)
    finally:
        con.close()


def _migrate_helpful_count():
    """genre_books に helpful_count カラムを追加する。"""
    if _migration_done("helpful_count_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE genre_books ADD COLUMN IF NOT EXISTS helpful_count INTEGER DEFAULT 0")
        else:
            try:
                con.execute("ALTER TABLE genre_books ADD COLUMN helpful_count INTEGER DEFAULT 0")
            except Exception:
                pass
        con.commit()
        _mark_migration_done("helpful_count_v1")
        logger.info("[migration] genre_books.helpful_count カラム追加完了")
    except Exception as e:
        logger.error("[migration] helpful_count error: %s", e)
    finally:
        con.close()


def _migrate_helpful_votes():
    """helpful_votes テーブルを追加する（重複投票防止）。"""
    if _migration_done("helpful_votes_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS helpful_votes (
                    isbn TEXT NOT NULL,
                    voter_hash TEXT NOT NULL,
                    voted_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (isbn, voter_hash)
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS helpful_votes (
                    isbn TEXT NOT NULL,
                    voter_hash TEXT NOT NULL,
                    voted_at TEXT DEFAULT (datetime('now','localtime')),
                    PRIMARY KEY (isbn, voter_hash)
                )
            """)
        con.commit()
        _mark_migration_done("helpful_votes_v1")
        logger.info("[migration] helpful_votes テーブル追加完了")
    except Exception as e:
        logger.error("[migration] helpful_votes error: %s", e)
    finally:
        con.close()


def _migrate_ai_review_columns():
    """genre_books に ai_summary / ai_tags カラムを追加する。"""
    if _migration_done("ai_review_columns_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE genre_books ADD COLUMN IF NOT EXISTS ai_summary TEXT")
            cur.execute("ALTER TABLE genre_books ADD COLUMN IF NOT EXISTS ai_tags TEXT DEFAULT '[]'")
        else:
            try:
                con.execute("ALTER TABLE genre_books ADD COLUMN ai_summary TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE genre_books ADD COLUMN ai_tags TEXT DEFAULT '[]'")
            except Exception:
                pass
        con.commit()
        _mark_migration_done("ai_review_columns_v1")
        logger.info("[migration] genre_books.ai_summary/ai_tags カラム追加完了")
    except Exception as e:
        logger.error("[migration] ai_review_columns error: %s", e)
    finally:
        con.close()


def _migrate_ndc_column():
    """genre_books に ndc カラムを追加する。"""
    if _migration_done("ndc_column_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE genre_books ADD COLUMN IF NOT EXISTS ndc TEXT DEFAULT ''")
        else:
            try:
                con.execute("ALTER TABLE genre_books ADD COLUMN ndc TEXT DEFAULT ''")
            except Exception:
                pass
        con.commit()
        _mark_migration_done("ndc_column_v1")
        logger.info("[migration] genre_books.ndc カラム追加完了")
    except Exception as e:
        logger.error("[migration] ndc_column error: %s", e)
    finally:
        con.close()


def _migrate_award_books_plam_work_id():
    """award_books に plam_work_id カラムを追加する（PLAM連携用）。"""
    if _migration_done("award_books_plam_work_id_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE award_books ADD COLUMN IF NOT EXISTS plam_work_id TEXT DEFAULT NULL")
        else:
            try:
                con.execute("ALTER TABLE award_books ADD COLUMN plam_work_id TEXT DEFAULT NULL")
            except Exception:
                pass
        con.commit()
        _mark_migration_done("award_books_plam_work_id_v1")
        logger.info("[migration] award_books.plam_work_id カラム追加完了")
    except Exception as e:
        logger.error("[migration] award_books_plam_work_id error: %s", e)
    finally:
        con.close()


def _migrate_plam_coverage_log():
    """PLAMカバレッジ履歴テーブルを追加する。"""
    if _migration_done("plam_coverage_log_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS plam_coverage_log (
                    id SERIAL PRIMARY KEY,
                    logged_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    total INTEGER NOT NULL,
                    linked INTEGER NOT NULL,
                    coverage_pct REAL NOT NULL,
                    note TEXT DEFAULT NULL
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS plam_coverage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at TEXT NOT NULL DEFAULT (datetime('now')),
                    total INTEGER NOT NULL,
                    linked INTEGER NOT NULL,
                    coverage_pct REAL NOT NULL,
                    note TEXT DEFAULT NULL
                )
            """)
        con.commit()
        _mark_migration_done("plam_coverage_log_v1")
        logger.info("[migration] plam_coverage_log テーブル追加完了")
    except Exception as e:
        logger.error("[migration] plam_coverage_log error: %s", e)
    finally:
        con.close()


def _migrate_plam_fix_log():
    """PLAMオートフィックスログテーブルを追加する。"""
    if _migration_done("plam_fix_log_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS plam_fix_log (
                    id SERIAL PRIMARY KEY,
                    fixed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    award_book_id INTEGER NOT NULL,
                    award TEXT,
                    award_year INTEGER,
                    db_title TEXT,
                    db_author TEXT,
                    plam_work_id TEXT NOT NULL,
                    plam_title TEXT,
                    plam_author TEXT,
                    confidence REAL NOT NULL,
                    fix_type TEXT NOT NULL,
                    mode TEXT NOT NULL
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS plam_fix_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fixed_at TEXT NOT NULL DEFAULT (datetime('now')),
                    award_book_id INTEGER NOT NULL,
                    award TEXT,
                    award_year INTEGER,
                    db_title TEXT,
                    db_author TEXT,
                    plam_work_id TEXT NOT NULL,
                    plam_title TEXT,
                    plam_author TEXT,
                    confidence REAL NOT NULL,
                    fix_type TEXT NOT NULL,
                    mode TEXT NOT NULL
                )
            """)
        con.commit()
        _mark_migration_done("plam_fix_log_v1")
        logger.info("[migration] plam_fix_log テーブル追加完了")
    except Exception as e:
        logger.error("[migration] plam_fix_log error: %s", e)
    finally:
        con.close()


def _migrate_collections_sort_order():
    """collections テーブルに sort_order カラムがなければ追加する。"""
    if _migration_done("collections_sort_order_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("ALTER TABLE collections ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0")
        else:
            try:
                con.execute("ALTER TABLE collections ADD COLUMN sort_order INTEGER DEFAULT 0")
            except Exception:
                pass
        con.commit()
        _mark_migration_done("collections_sort_order_v1")
        logger.info("[migration] collections.sort_order カラム追加完了")
    except Exception as e:
        logger.error("[migration] collections_sort_order error: %s", e)
    finally:
        con.close()


def _migrate_loan_history():
    """貸出履歴テーブル（loan_history）を追加する。"""
    if _migration_done("loan_history_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS loan_history (
                    id SERIAL PRIMARY KEY,
                    isbn TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    recorded_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_loan_history_isbn ON loan_history(isbn)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_loan_history_recorded ON loan_history(recorded_at)")
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS loan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isbn TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    recorded_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_loan_history_isbn ON loan_history(isbn)")
        con.commit()
        _mark_migration_done("loan_history_v1")
        logger.info("[migration] loan_history テーブル追加完了")
    except Exception as e:
        logger.error("[migration] loan_history error: %s", e)
    finally:
        con.close()


def _migrate_sync_plam_to_award_books():
    """PLAM CSV (award_history.csv + works.csv) を award_books に同期する。"""
    if _migration_done("sync_plam_to_award_books_v2"):
        return
    if not USE_PG:
        return

    import csv
    import unicodedata
    import os

    AWARD_MAP = {
        "AKU": "芥川賞", "NAO": "直木賞", "JRA": "日本推理作家協会賞",
        "HKM": "本格ミステリ大賞", "HON": "本屋大賞", "YAM": "山本周五郎賞",
        "KMS": "このミステリーがすごい！国内1位", "RAN": "江戸川乱歩賞",
        "KIK": "吉川英治文学賞", "JSF": "日本SF大賞", "HOR": "日本ホラー小説大賞",
    }

    def _n(s):
        s = unicodedata.normalize("NFKC", s or "").strip()
        return "".join(s.split())

    base = os.path.join(os.path.dirname(__file__), "data", "plam")
    try:
        works = {r["work_id"]: r for r in csv.DictReader(open(os.path.join(base, "works.csv"), encoding="utf-8"))}
        history = list(csv.DictReader(open(os.path.join(base, "award_history.csv"), encoding="utf-8")))
    except Exception as e:
        logger.error("[migration] sync_plam: CSV読み込みエラー: %s", e)
        return

    con = get_con()
    try:
        existing_rows = fetchall(con, "SELECT award, title FROM award_books")
        existing = {(_n(r["title"]), r["award"]) for r in existing_rows}
        logger.info("[migration] sync_plam: 既存 %d件、history %d件", len(existing_rows), len(history))

        inserted = 0
        for row in history:
            award_name = AWARD_MAP.get(row["award_id"])
            if not award_name:
                continue
            work = works.get(row["work_id"])
            if not work:
                continue
            title = (work.get("canonical_title") or work.get("title") or "").strip()
            if not title:
                continue
            author = (work.get("author") or "").strip()
            isbn13 = work.get("isbn13", "").strip() or None
            award_year = int(row["award_year"]) if row.get("award_year") else None
            award_no = int(row["award_no"]) if row.get("award_no") else None

            if (_n(title), award_name) in existing:
                continue

            execute(con,
                "INSERT INTO award_books (award, award_no, award_year, title, author, isbn13, status) VALUES (?,?,?,?,?,?,?)",
                (award_name, award_no, award_year, title, author, isbn13, "確認済"),
            )
            existing.add((_n(title), award_name))
            inserted += 1

        con.commit()
        _mark_migration_done("sync_plam_to_award_books_v2")
        logger.info("[migration] PLAM→award_books 同期完了: %d件追加", inserted)
    except Exception as e:
        logger.error("[migration] sync_plam_to_award_books error: %s", e, exc_info=True)
    finally:
        con.close()


def _migrate_fetch_isbn_ndl():
    """award_books の isbn13 が空のエントリを NDL API で補完する（バックグラウンド）。"""
    if _migration_done("fetch_isbn_ndl_v1"):
        return
    if not USE_PG:
        return

    def _run():
        import time
        import re
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET
        import unicodedata

        def _norm(s):
            return unicodedata.normalize("NFKC", s or "").strip()

        def _isbn10_to_13(digits10):
            if len(digits10) != 10:
                return None
            base = "978" + digits10[:9]
            total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))
            return base + str((10 - (total % 10)) % 10)

        def _extract_isbns(item, ns):
            seen, jp, other = set(), [], []
            for ident in item.findall("dc:identifier", ns):
                digits = re.sub(r"[^0-9X]", "", (ident.text or "").upper())
                if digits in seen:
                    continue
                seen.add(digits)
                isbn13 = None
                if len(digits) == 13 and digits.startswith("978"):
                    isbn13 = digits
                elif len(digits) == 10:
                    isbn13 = _isbn10_to_13(digits)
                if isbn13:
                    (jp if isbn13.startswith("9784") else other).append(isbn13)
            return jp + other

        def _ndl_search(title_n, author_n):
            params = {"title": title_n, "cnt": "8"}
            if author_n:
                params["creator"] = author_n
            url = "https://ndlsearch.ndl.go.jp/api/opensearch?" + urllib.parse.urlencode(params)
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    xml_text = r.read().decode("utf-8")
            except Exception:
                return None
            tree = ET.fromstring(xml_text)
            ns = {"dc": "http://purl.org/dc/elements/1.1/"}
            jp_res, fallback = [], []
            for item in tree.findall(".//item"):
                t_el = item.find("title")
                t = _norm(t_el.text or "") if t_el is not None else ""
                isbns = _extract_isbns(item, ns)
                if not isbns:
                    continue
                match_len = min(len(title_n), 6)
                if title_n[:match_len] and t.startswith(title_n[:match_len]):
                    jp_res.extend(isbns)
                elif title_n in t or (len(title_n) >= 2 and t.startswith(title_n[:2])):
                    fallback.extend(isbns)
            for isbn in jp_res:
                if isbn.startswith("9784"):
                    return isbn
            if jp_res:
                return jp_res[0]
            for isbn in fallback:
                if isbn.startswith("9784"):
                    return isbn
            return fallback[0] if fallback else None

        con = get_con()
        try:
            rows = fetchall(
                con,
                "SELECT id, title, author FROM award_books WHERE (isbn13 IS NULL OR isbn13='') AND status='確認済' ORDER BY award_year DESC NULLS LAST, id",
            )
        finally:
            con.close()

        logger.info("[migration] NDL ISBN補完: %d件対象", len(rows))
        found = 0
        for row in rows:
            title_n = _norm(row["title"])
            author_n = _norm(row["author"] or "")
            isbn = _ndl_search(title_n, author_n)
            if not isbn:
                time.sleep(0.3)
                isbn = _ndl_search(title_n, None)
            if isbn:
                con2 = get_con()
                try:
                    execute(con2, "UPDATE award_books SET isbn13=%s WHERE id=%s", (isbn, row["id"]))
                    con2.commit()
                    found += 1
                finally:
                    con2.close()
            time.sleep(0.6)

        _mark_migration_done("fetch_isbn_ndl_v1")
        logger.info("[migration] NDL ISBN補完完了: %d件取得", found)

    threading.Thread(target=_run, daemon=True).start()


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
        _migrate_my_loans,             # マイ貸出リスト（返却リマインダー用）※重い処理の前に確実に作成
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
        _migrate_reading_timeline,     # 読書タイムライン
        _migrate_newsletters,          # 図書館だより
        _migrate_collections_sort_order,  # collections.sort_order カラム追加
        _migrate_events_image,             # events.image_data カラム追加
        _migrate_update_award_isbn,        # 受賞作ISBN一括更新
        _migrate_helpful_count,            # helpful_count カラム追加
        _migrate_helpful_votes,            # helpful_votes テーブル追加
        _migrate_ai_review_columns,        # ai_summary/ai_tags カラム追加
        _migrate_ndc_column,               # ndc カラム追加
        _migrate_award_books_plam_work_id, # award_books.plam_work_id カラム追加
        _migrate_plam_coverage_log,        # PLAMカバレッジ履歴テーブル追加
        _migrate_plam_fix_log,             # PLAMオートフィックスログテーブル追加
        _migrate_loan_history,             # 貸出履歴テーブル追加
        _migrate_sync_plam_to_award_books, # PLAM CSV → award_books 同期
        _migrate_fetch_isbn_ndl,           # NDL API で isbn13 補完（バックグラウンド）
        _migrate_db_indices,               # パフォーマンス用インデックス
        _verify_tables,
    ]
    for step in steps:
        try:
            step()
        except Exception as e:
            logger.error(f"[migration error] {step.__name__}: %s", e)


def _migrate_my_loans():
    """my_loans テーブルを追加（住民の自己申告貸出・返却期限リマインダー用）。"""
    if _migration_done("my_loans_v1"):
        return
    con = get_con()
    try:
        if USE_PG:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS my_loans (
                    id SERIAL PRIMARY KEY,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    due_date DATE,
                    reminder_sent_at TIMESTAMPTZ,
                    returned_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(room, isbn)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_my_loans_due ON my_loans(due_date) WHERE returned_at IS NULL")
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS my_loans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT NOT NULL,
                    isbn TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    due_date DATE,
                    reminder_sent_at TIMESTAMP,
                    returned_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(room, isbn)
                )
            """)
        con.commit()
        _mark_migration_done("my_loans_v1")
        logger.info("[migration] my_loans テーブル追加完了")
    except Exception as e:
        logger.error(f"[migration] my_loans error: %s", e)
    finally:
        con.close()


def _migrate_db_indices():
    """パフォーマンス改善用インデックスを追加する"""
    try:
        con = get_con()
        indices = [
            "CREATE INDEX IF NOT EXISTS idx_genre_books_genre ON genre_books(genre)",
            "CREATE INDEX IF NOT EXISTS idx_requests_status ON book_requests(status)",
            "CREATE INDEX IF NOT EXISTS idx_requests_type ON book_requests(type)",
        ]
        for sql in indices:
            try:
                if USE_PG:
                    cur = con.cursor()
                    cur.execute(sql)
                else:
                    con.execute(sql)
                con.commit()
            except Exception:
                try:
                    con.rollback()
                except Exception:
                    pass
        con.close()
    except Exception as e:
        logger.error("[migration] _migrate_db_indices: %s", e)


def _ensure_db():
    try:
        init_db()
    except Exception as e:
        logger.error(f"DB init error: %s", e)
    threading.Thread(target=_run_all_migrations, daemon=True).start()
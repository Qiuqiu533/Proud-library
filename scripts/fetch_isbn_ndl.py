"""
NDL API で award_books の isbn13 を補完するスクリプト。
実行: DATABASE_URL=... python3 scripts/fetch_isbn_ndl.py [--dry-run] [--limit N]

- isbn13 が空の award_books エントリを対象に NDL を検索
- 日本語 ISBN（978-4）を優先して取得
- 1リクエストごと 0.6 秒スリープ（NDL 利用規約に配慮）
"""
import os
import sys
import time
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import unicodedata

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()

def isbn10_to_13(isbn10: str) -> str | None:
    digits = re.sub(r"[^0-9X]", "", isbn10.upper())
    if len(digits) != 10:
        return None
    base = "978" + digits[:9]
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))
    check = (10 - (total % 10)) % 10
    return base + str(check)

def _extract_isbns(item, ns):
    """item の dc:identifier から ISBN13 候補リストを返す（978-4 優先）。"""
    candidates_jp = []
    candidates_other = []
    seen = set()
    for ident in item.findall("dc:identifier", ns):
        raw = (ident.text or "").strip()
        # ハイフンを除去して数字列を取得
        digits = re.sub(r"[^0-9X]", "", raw.upper())
        if digits in seen:
            continue
        seen.add(digits)

        isbn13 = None
        if len(digits) == 13 and digits[:3] == "978":
            isbn13 = digits
        elif len(digits) == 10:
            isbn13 = isbn10_to_13(digits)

        if isbn13:
            (candidates_jp if isbn13.startswith("9784") else candidates_other).append(isbn13)

    return candidates_jp + candidates_other

def _search_ndl(title: str, author: str | None) -> str | None:
    """NDL に1回検索して最良の ISBN13 を返す。"""
    title_n = _norm(title)
    params: dict = {"title": title_n, "cnt": "8"}
    if author:
        params["creator"] = _norm(author)
    url = "https://ndlsearch.ndl.go.jp/api/opensearch?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            xml_text = r.read().decode("utf-8")
    except Exception:
        return None

    tree = ET.fromstring(xml_text)
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}

    jp_results: list[str] = []
    fallback: list[str] = []

    for item in tree.findall(".//item"):
        item_title_el = item.find("title")
        item_title = _norm(item_title_el.text or "") if item_title_el is not None else ""
        isbns = _extract_isbns(item, ns)
        if not isbns:
            continue
        # タイトル一致判定：前方一致・部分一致・逆包含の3段階
        t_short = title_n[:4] if len(title_n) >= 4 else title_n
        is_match = (
            item_title.startswith(t_short)          # NDLタイトルが入力タイトルで始まる
            or title_n in item_title                 # NDLタイトルに入力タイトルが含まれる
            or item_title in title_n                 # 入力タイトルにNDLタイトルが含まれる（例: "64"→"64(ロクヨン)"）
        )
        is_strong = item_title.startswith(title_n[:min(len(title_n), 6)])
        if is_strong:
            jp_results.extend(isbns)
        elif is_match:
            fallback.extend(isbns)

    for isbn in jp_results:
        if isbn.startswith("9784"):
            return isbn
    if jp_results:
        return jp_results[0]
    for isbn in fallback:
        if isbn.startswith("9784"):
            return isbn
    return fallback[0] if fallback else None


def ndl_isbn(title: str, author: str) -> str | None:
    """タイトル+著者で検索し、見つからなければタイトルのみで再試行。"""
    result = _search_ndl(title, author)
    if result:
        return result
    time.sleep(0.3)
    # フォールバック: タイトルのみ
    return _search_ndl(title, None)

def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from database import get_con, execute, fetchall

    con = get_con()
    rows = fetchall(
        con,
        "SELECT id, title, author FROM award_books WHERE (isbn13 IS NULL OR isbn13 = '') AND status='確認済' ORDER BY id",
    )
    con.close()

    print(f"ISBN未設定 {len(rows)} 件を処理します（dry_run={dry_run}）")
    if limit:
        rows = rows[:limit]
        print(f"  → --limit {limit} で絞り込み")

    found = 0
    not_found = 0

    for i, row in enumerate(rows, 1):
        title = row["title"]
        author = row["author"] or ""
        isbn = ndl_isbn(title, author)

        if isbn:
            print(f"  [{i}] ✅ {title} / {author} → {isbn}")
            if not dry_run:
                con2 = get_con()
                execute(con2, "UPDATE award_books SET isbn13=? WHERE id=?", (isbn, row["id"]))
                con2.commit()
                con2.close()
            found += 1
        else:
            print(f"  [{i}] ❌ {title} / {author}")
            not_found += 1

        time.sleep(0.6)

    print(f"\n完了: 取得 {found} 件 / 未取得 {not_found} 件")

if __name__ == "__main__":
    main()

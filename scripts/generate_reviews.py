"""
AI書評生成スクリプト v2
モデル: gpt-4o-mini
改善点:
  - few-shot例示（良い書評の見本）
  - temperature 0.7（表現の多様性向上）
  - Wikipedia著者情報取得
  - 1文60字以内ルール
  - 情報不足の場合は生成しない
  - 3要素必須（概要・読みどころ・対象読者）
  - AI自己採点で70点未満は再生成
  - 書評・一言紹介・タグを同時出力
  - 400〜600字の長さ

使い方:
  cd /tmp/Proud-library-fresh
  set -a && source .env.review && set +a
  python3 scripts/generate_reviews.py [--dry-run] [--limit N] [--isbn ISBN] [--regen]

オプション:
  --dry-run    DBを更新しない
  --limit N    処理件数（デフォルト50）
  --isbn ISBN  特定ISBNのみ処理
  --regen      既存書評も上書き再生成（ai_review_scoreがNULLのものが対象）
  --min-len N  この文字数未満を再生成対象に（デフォルト100）
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import json
import re
import requests
import datetime

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MODEL = "gpt-4o-mini"

# ============================
# few-shot 良い書評の見本
# ============================
FEW_SHOT_EXAMPLE = """
【見本】
書名: たのしいムーミン一家 / トーベ・ヤンソン / ジャンル: 文芸小説

一言紹介: 北欧の幻想世界で家族と仲間の絆を描く温かな物語。
タグ: 家族, 友情, 自然, 北欧文学, 翻訳

書評:
北欧フィンランドの作家トーベ・ヤンソンが生み出した、ムーミン谷を舞台にした心温まる物語。
四季の移り変わりとともに、ムーミン一家と個性豊かな仲間たちが繰り広げる冒険や日常が瑞々しく描かれる。
友情・家族の絆・自然との共生という普遍的なテーマを、ユーモアと詩情を交えて語りかけてくる。
訳文も平易で読みやすく、子どもから大人まで世代を問わず楽しめる一冊だ。
子どもへの読み聞かせとしても、大人が懐かしさを感じながら再読するのにも最適な名作シリーズ。
---
"""


def _get_con():
    """プールを使わず直接1接続だけ確立する"""
    if DATABASE_URL:
        import psycopg2
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        con = psycopg2.connect(url)
        con.autocommit = False
        return con, "%s"
    else:
        import sqlite3
        con = sqlite3.connect(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.db"))
        con.row_factory = sqlite3.Row
        return con, "?"


def _fetch_wikipedia_author(author: str) -> str:
    """Wikipedia日本語版から著者情報を取得する（フルネーム優先）"""
    if not author:
        return ""
    # フルネーム → 姓のみ の順で試みる
    candidates = []
    full = author.strip().replace("　", " ")
    candidates.append(full)
    parts = full.split()
    if len(parts) > 1:
        candidates.append(parts[0])  # 姓のみ

    for name in candidates:
        try:
            res = requests.get(
                f"https://ja.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(name)}",
                timeout=8,
                headers={"User-Agent": "ProudLibrary/1.0"}
            )
            if res.status_code == 200:
                data = res.json()
                # 人物記事かどうか確認（descriptionに「作家」「小説家」「詩人」等が含まれるか）
                description = data.get("description", "")
                extract = data.get("extract", "")
                person_keywords = ["作家", "小説家", "詩人", "著者", "ライター", "絵本", "漫画", "画家",
                                   "教授", "研究者", "評論家", "脚本家", "翻訳家", "医師", "写真家"]
                is_person = any(kw in description or kw in extract[:100] for kw in person_keywords)
                if is_person:
                    sentences = extract.replace("。", "。\n").split("\n")
                    summary = "。".join([s for s in sentences[:2] if s.strip()])
                    if summary and len(summary) > 10:
                        return summary[:200]
        except Exception:
            pass
    return ""


def _fetch_openbd_meta(isbn: str) -> dict:
    """OpenBDから書誌情報を取得する"""
    try:
        res = requests.get(f"https://api.openbd.jp/v1/get?isbn={isbn}", timeout=10)
        data = res.json()
        if data and data[0]:
            summary = data[0].get("summary", {})
            return {
                "title": summary.get("title", ""),
                "author": summary.get("author", ""),
                "publisher": summary.get("publisher", ""),
                "pubdate": summary.get("pubdate", ""),
            }
    except Exception:
        pass
    return {}


def _generate_review(title: str, author: str, publisher: str, genre: str,
                     wiki_info: str, attempt: int = 1) -> dict | None:
    """
    OpenAI APIで書評を生成する。
    戻り値: {"review": str, "summary": str, "tags": list, "score": int} or None（情報不足）
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY が設定されていません")

    wiki_section = f"\n著者情報（Wikipedia）: {wiki_info}" if wiki_info else ""

    prompt = f"""{FEW_SHOT_EXAMPLE}
上の見本を参考に、以下の書籍の書評をJSON形式で出力してください。

書名: {title}
著者: {author or "不明"}{wiki_section}
出版社: {publisher or "不明"}
ジャンル: {genre or "その他"}

【必須ルール】
1. 提供された情報（書名・著者・出版社・著者情報）に基づいてのみ書く。知らない・確認できない内容は絶対に書かない
2. 書名から内容を推測・想像して書くことは禁止。書名はあくまで参考情報
3. 書評の文字数は得られた情報量に応じて150〜500字で調整してよい（情報が少なければ短くてよい）
4. 書ける範囲で以下の要素を含める（情報がなければ省略可）:
   ① 書籍の概要・テーマ（確認できる事実のみ）
   ② 著者について（著者情報がある場合のみ）
   ③ 対象読者（ジャンルから明らかな範囲のみ）
5. 1文は60字以内に収める（長い文は2文に分ける）
6. 特定の政治・宗教・思想的立場を推奨・批判しない
7. 最後に自己採点スコア（0〜100点）を付ける（基準：事実のみ記載=+40、読者に有益な情報=+30、読みやすい文体=+30）

出力はJSON形式のみ（説明文は不要）:
{{
  "status": "ok",
  "review": "書評本文（400〜600字）",
  "summary": "一言紹介（50字以内）",
  "tags": ["タグ1", "タグ2", "タグ3"],
  "score": 採点スコア（0〜100の整数）
}}"""

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=40,
    )
    res.raise_for_status()
    content = res.json()["choices"][0]["message"]["content"].strip()

    data = json.loads(content)

    if data.get("status") == "情報不足":
        return None

    return {
        "review": data.get("review", ""),
        "summary": data.get("summary", ""),
        "tags": data.get("tags", []),
        "score": int(data.get("score", 0)),
    }


def main():
    parser = argparse.ArgumentParser(description="AI書評生成スクリプト v2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--isbn", type=str, default="")
    parser.add_argument("--regen", action="store_true", help="ai_review_scoreがNULLの既存書評も再生成")
    parser.add_argument("--min-len", type=int, default=100)
    parser.add_argument("--min-score", type=int, default=70, help="この点未満は再生成（デフォルト70）")
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY 環境変数を設定してください")
        sys.exit(1)

    con, PH = _get_con()
    cur = con.cursor()

    if args.isbn:
        cur.execute(
            f"SELECT isbn, title, author, publisher, genre, description FROM genre_books WHERE isbn={PH}",
            (args.isbn,)
        )
    elif args.regen:
        # ai_review_scoreがNULL（以前の書評）を再生成対象に
        cur.execute(f"""SELECT isbn, title, author, publisher, genre, description
                FROM genre_books
                WHERE (manual_review IS NULL OR manual_review = FALSE)
                  AND ai_review_date IS NOT NULL
                  AND ai_review_score IS NULL
                ORDER BY isbn
                LIMIT {args.limit}""")
    else:
        cur.execute(f"""SELECT isbn, title, author, publisher, genre, description
                FROM genre_books
                WHERE (manual_review IS NULL OR manual_review = FALSE)
                  AND (description IS NULL OR LENGTH(description) < {args.min_len})
                ORDER BY isbn
                LIMIT {args.limit}""")

    if DATABASE_URL:
        books = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    else:
        books = [dict(row) for row in cur.fetchall()]

    print(f"対象: {len(books)} 件  dry-run: {args.dry_run}  regen: {args.regen}")

    success = 0
    skipped = 0
    fail = 0

    for book in books:
        isbn = book["isbn"]
        title = book["title"] or ""
        author = book["author"] or ""
        publisher = book["publisher"] or ""
        genre = book["genre"] or ""

        print(f"\n[{isbn}] {title} / {author}")

        # OpenBD補足情報
        meta = _fetch_openbd_meta(isbn)
        if meta.get("publisher") and not publisher:
            publisher = meta["publisher"]

        # Wikipedia著者情報
        wiki_info = _fetch_wikipedia_author(author)
        if wiki_info:
            print(f"  📖 Wikipedia: {wiki_info[:60]}...")

        try:
            # 最大2回試行（低スコアなら再生成）
            result = None
            for attempt in range(1, 3):
                result = _generate_review(title, author, publisher, genre, wiki_info, attempt)

                if result is None:
                    print(f"  ⚠️ 情報不足のためスキップ")
                    skipped += 1
                    break

                print(f"  → {result['review'][:80]}...")
                print(f"  一言: {result['summary']}")
                print(f"  タグ: {', '.join(result['tags'])}")
                print(f"  自己採点: {result['score']}/100")

                if result["score"] >= args.min_score:
                    break
                elif attempt == 1:
                    print(f"  ⚠️ スコア{result['score']}点 < {args.min_score}点 → 再生成")
                    time.sleep(1)

            if result is None:
                continue

            if not args.dry_run:
                today = datetime.date.today().isoformat()
                tags_json = json.dumps(result["tags"], ensure_ascii=False)
                cur.execute(
                    f"""UPDATE genre_books
                        SET description={PH}, ai_review_date={PH}, ai_review_score={PH},
                            ai_model={PH}, ai_summary={PH}, ai_tags={PH}
                        WHERE isbn={PH}""",
                    (result["review"], today, result["score"], MODEL,
                     result["summary"], tags_json, isbn),
                )
                con.commit()
                print("  ✅ DB更新完了")
            success += 1

        except Exception as e:
            print(f"  ❌ エラー: {e}")
            fail += 1

        time.sleep(0.5)

    con.close()
    print(f"\n完了: 成功 {success} 件 / スキップ {skipped} 件 / 失敗 {fail} 件")


if __name__ == "__main__":
    main()

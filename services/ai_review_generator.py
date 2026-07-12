"""AI書評（description/ai_summary/ai_tags）生成の共通ロジック。

2026-07-08: scripts/generate_reviews.py（CLI専用・手動実行）のロジックを
ここに切り出し、管理画面からの半自動再生成でも同じコードを使えるようにした。
DeepSeekでの想定外課金・OpenAI $11課金の反省を踏まえ、管理画面からの実行は
「完全自動」ではなく「管理者が概算コストを確認してから明示的に起動する」
Phase 1（半自動）のみをサポートする。1ジョブあたり最大100件に制限。

Phase 2（新規登録・ISBN修復時にキューへ追加するだけ）、Phase 3（夜間の
完全自動実行・月間予算上限）は将来の拡張として見送り。
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import threading
import time
import datetime

import requests

from database import get_con, execute, fetchall, fetchone, USE_PG
from services.ai_review_validator import validate_review

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = "gpt-4o-mini"

# gpt-4o-mini 概算料金（2026-07時点。正確な最新料金はOpenAI公式サイトで確認すること）
_PRICE_PER_1M_INPUT_USD = 0.15
_PRICE_PER_1M_OUTPUT_USD = 0.60
_USD_TO_JPY = 155  # 概算レート。あくまで見積り用途で厳密な為替ではない
_EST_INPUT_TOKENS_PER_BOOK = 900   # few-shot例示込みプロンプトの概算
_EST_OUTPUT_TOKENS_PER_BOOK = 500  # 書評400〜600字+JSON構造の概算

_JOB_MAX_LIMIT = 100  # 1ジョブあたりの上限（安全装置）
_MIN_LEN_DEFAULT = 100
_MIN_SCORE_DEFAULT = 70
_MIN_CONFIDENCE = 60  # これ未満のconfidenceは創作の疑いが強いため生成を破棄する

OPENING_PATTERNS = [
    "「『{title}』は、」のように書名を主語にして始める",
    "「{title}という作品は、」のように書名を作品名として紹介する形で始める",
    "「本作『{title}』では、」のように本作という語で始める",
    "「この作品は、」のように書名を繰り返さず始める",
    "「{title}は、〜を描いた作品です。」のように簡潔な定義文で始める",
    "「読者に〜を問いかける作品として、{title}は」のように読者への問いかけから始める",
    "「{author}による『{title}』は、」のように著者名を主語にして始める",
]


def _format_pubdate(pubdate: str) -> str:
    """OpenBDのpubdate（例: "201609"）を "2016年" 形式に整形する。"""
    if not pubdate or len(pubdate) < 4:
        return ""
    return f"{pubdate[:4]}年"


def _format_awards(awards_raw) -> str:
    """genre_books.awardsカラム（JSON文字列 or リスト）を人間可読な文字列に整形する。

    2026-07-11: award_books由来の自前データは公式情報で照合済みの高信頼データ
    のため、書誌情報拡充の中でも特に効果が大きい（推測に頼らず断定的に書ける）。
    """
    if not awards_raw:
        return ""
    try:
        awards = json.loads(awards_raw) if isinstance(awards_raw, str) else awards_raw
    except Exception:
        return ""
    if not isinstance(awards, list) or not awards:
        return ""
    parts = []
    for a in awards:
        if not isinstance(a, dict):
            continue
        year = a.get("year", "")
        name = a.get("award", "")
        rank = a.get("rank")
        if not name:
            continue
        label = f"{year}年{name}" if year else name
        if rank:
            label += f"（{rank}位）"
        parts.append(label)
    return "、".join(parts)


def _opening_pattern_for_isbn(isbn: str) -> str:
    """ISBNから決定的に書き出しパターンを選ぶ（同じ本は毎回同じ書き出しになる）。

    2026-07-11: 35冊検証で「『Xは、Yによる〜』」という書き出しが74%を占める
    テンプレート化が判明。本文の構成・安全性ルールは変えず、書き出しの
    指示だけを複数用意してISBNのハッシュ値で決定的に選択することで、
    多様性を確保しつつ再生成のたびに結果がぶれないようにする。
    """
    idx = int(hashlib.md5(isbn.encode("utf-8")).hexdigest(), 16) % len(OPENING_PATTERNS)
    return OPENING_PATTERNS[idx]


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


def fetch_wikipedia_author(author: str) -> str:
    """Wikipedia日本語版から著者情報を取得する（フルネーム優先）"""
    if not author:
        return ""
    candidates = []
    full = author.strip().replace("　", " ")
    candidates.append(full)
    parts = full.split()
    if len(parts) > 1:
        candidates.append(parts[0])

    for name in candidates:
        try:
            res = requests.get(
                f"https://ja.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(name)}",
                timeout=8,
                headers={"User-Agent": "ProudLibrary/1.0"}
            )
            if res.status_code == 200:
                data = res.json()
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


def fetch_openbd_meta(isbn: str) -> dict:
    """OpenBDから書誌情報を取得する。

    2026-07-09: 「風姿花伝」（世阿弥の古典、馬場あき子は現代語訳・注釈者）を
    「馬場あき子によるミステリ・推理小説」と完全に事実と異なる内容で生成する
    ハルシネーション事故が発生。genre_books.authorだけでは「原著者」なのか
    「現代語訳・注釈者」なのか判別できないため、OpenBDのシリーズ名
    （例:「古典を読む」）と原著の内容紹介文（CollateralDetail）が取得できる
    場合はそれもプロンプトへ渡し、事実に基づかない創作を減らす。
    """
    try:
        res = requests.get(f"https://api.openbd.jp/v1/get?isbn={isbn}", timeout=10)
        data = res.json()
        if data and data[0]:
            summary = data[0].get("summary", {})
            onix = data[0].get("onix", {})
            descriptive = onix.get("DescriptiveDetail", {}) if isinstance(onix, dict) else {}

            series = ""
            try:
                elements = descriptive.get("Collection", {}).get("TitleDetail", {}).get("TitleElement", [])
                if isinstance(elements, dict):
                    elements = [elements]
                for el in elements:
                    t = (el.get("TitleText") or {}).get("content", "")
                    if t:
                        series = t
                        break
            except Exception:
                pass

            blurb = ""
            try:
                collateral = onix.get("CollateralDetail", {}) if isinstance(onix, dict) else {}
                for tc in collateral.get("TextContent", []) or []:
                    text = (tc.get("Text") or "").strip()
                    if text:
                        blurb = text
                        break
            except Exception:
                pass

            return {
                "title": summary.get("title", ""),
                "author": summary.get("author", ""),
                "publisher": summary.get("publisher", ""),
                "pubdate": summary.get("pubdate", ""),
                "series": series,
                "blurb": blurb,
            }
    except Exception:
        pass
    return {}


def call_openai_review(title: str, author: str, publisher: str, genre: str, wiki_info: str,
                        series: str = "", blurb: str = "", isbn: str = "",
                        pubdate: str = "", awards_text: str = "") -> dict | None:
    """OpenAI APIで書評を1回生成する。戻り値: dict または情報不足でNone。

    2026-07-09: 「風姿花伝」（世阿弥の古典、馬場あき子は現代語訳・注釈者）を
    「馬場あき子によるミステリ・推理小説」という完全な虚偽内容で生成する事故が
    発生。タイトル・著者名だけの乏しい情報でもLLMは「それらしい創作」を
    自信満々に補完してしまう傾向があるため、(1)シリーズ名等の追加手がかりを
    渡す、(2)古典・翻訳・注釈書は創作してはいけない旨を明記する、
    (3)自己採点だけでなくconfidence（確信度）を出力させ、低い場合は
    具体的な筋書きを書かせず一般的な位置づけの説明に留める、という3段構えで
    対策する。"""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY が設定されていません")

    wiki_section = f"\n著者情報（Wikipedia）: {wiki_info}" if wiki_info else ""
    series_section = f"\nシリーズ名: {series}" if series else ""
    blurb_section = f"\n出版社による紹介文: {blurb}" if blurb else ""
    pubdate_section = f"\n初版年: {pubdate}" if pubdate else ""
    awards_section = f"\n受賞歴: {awards_text}" if awards_text else ""
    opening_instruction = (_opening_pattern_for_isbn(isbn).format(title=title, author=author or "不明")
                            if isbn else "")
    opening_section = f"\n12. 書評の書き出しは、{opening_instruction}" if opening_instruction else ""
    awards_rule = ("\n11. 受賞歴が提供されている場合、それは事前に検証済みの確実な事実である。"
                    "書評に含めてよく、確信度を下げる要因にしない。" if awards_text else "")

    prompt = f"""{FEW_SHOT_EXAMPLE}
上の見本を参考に、以下の書籍の書評をJSON形式で出力してください。

書名: {title}
著者: {author or "不明"}{wiki_section}
出版社: {publisher or "不明"}
ジャンル: {genre or "その他"}{series_section}{blurb_section}{pubdate_section}{awards_section}

【必須ルール】
1. 提供された情報（書名・著者・出版社・著者情報・シリーズ名・紹介文・初版年・受賞歴）に基づいてのみ書く。知らない・確認できない内容は絶対に書かない
2. 書名から内容を推測・想像して書くことは禁止。書名はあくまで参考情報
3. 「著者」欄は原著者とは限らない（古典の現代語訳者・注釈者・編者・翻訳者の場合がある）。著者欄の人物が実際に何を書いたか確信できない場合、その人物が創作した物語であるかのように書いてはいけない
4. 古典・翻訳作品・全集・評論・研究書・注釈書である可能性がある場合（シリーズ名に「古典」「文学全集」等が含まれる、出版年が古い、等）、具体的な物語の筋書きを創作してはいけない。その場合は作品の位置づけ・ジャンル・歴史的背景など確認できる範囲の情報のみを書く
5. 書評の文字数は得られた情報量に応じて150〜500字で調整してよい（情報が少なければ短くてよい）
6. 書ける範囲で以下の要素を含める（情報がなければ省略可）:
   ① 書籍の概要・テーマ（確認できる事実のみ）
   ② 著者について（著者情報がある場合のみ）
   ③ 対象読者（ジャンルから明らかな範囲のみ）
7. 1文は60字以内に収める（長い文は2文に分ける）
8. 特定の政治・宗教・思想的立場を推奨・批判しない
9. confidence（この内容がどの程度事実に基づいていると確信できるか、0〜100）を出力する。書名・著者だけから内容を推測した部分が多い場合はconfidenceを50以下にする
10. 自己採点スコア（0〜100点）を付ける（基準：事実のみ記載=+40、読者に有益な情報=+30、読みやすい文体=+30）{awards_rule}{opening_section}

出力はJSON形式のみ（説明文は不要）:
{{
  "status": "ok",
  "review": "書評本文（400〜600字）",
  "summary": "一言紹介（50字以内）",
  "tags": ["タグ1", "タグ2", "タグ3"],
  "score": 採点スコア（0〜100の整数）,
  "confidence": 確信度（0〜100の整数）
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

    confidence = int(data.get("confidence", 100))
    if confidence < _MIN_CONFIDENCE:
        # 確信度が低い＝具体的な内容の大半が推測の可能性が高いため、
        # 創作された筋書きを保存せず「情報不足」として扱う（安全側に倒す）
        logger.info(f"AI書評: confidence={confidence}が閾値未満のため生成を破棄")
        return None

    return {
        "review": data.get("review", ""),
        "summary": data.get("summary", ""),
        "tags": data.get("tags", []),
        "score": int(data.get("score", 0)),
        "confidence": confidence,
    }


def generate_with_retry(title: str, author: str, publisher: str, genre: str, wiki_info: str,
                         min_score: int = _MIN_SCORE_DEFAULT, series: str = "", blurb: str = "",
                         isbn: str = "", pubdate: str = "", awards_text: str = "") -> dict | None:
    """スコアがmin_score未満なら1回だけ再生成する（最大2回試行）。confidence不足
    （ハルシネーション疑い）の場合はcall_openai_review内でNoneが返る。"""
    result = None
    for attempt in range(1, 3):
        result = call_openai_review(title, author, publisher, genre, wiki_info, series, blurb, isbn,
                                     pubdate, awards_text)
        if result is None:
            return None
        if result["score"] >= min_score or attempt == 2:
            break
        time.sleep(1)
    return result


def regenerate_one(isbn: str, book: dict, min_score: int = _MIN_SCORE_DEFAULT) -> dict:
    """1冊分の書評を生成しDBへ保存する。呼び出し元がconをcommit/closeする前提はない
    （この関数内で個別にDB接続・commitを行う）。

    戻り値: {"ok": True} / {"ok": False, "reason": "情報不足"} / {"ok": False, "error": str}
    """
    title = book.get("title") or ""
    author = book.get("author") or ""
    publisher = book.get("publisher") or ""
    genre = book.get("genre") or ""

    meta = fetch_openbd_meta(isbn)
    if meta.get("publisher") and not publisher:
        publisher = meta["publisher"]
    series = meta.get("series", "")
    blurb = meta.get("blurb", "")
    pubdate = _format_pubdate(meta.get("pubdate", ""))
    awards_text = _format_awards(book.get("awards"))

    wiki_info = fetch_wikipedia_author(author)

    try:
        result = generate_with_retry(title, author, publisher, genre, wiki_info, min_score, series, blurb, isbn,
                                      pubdate, awards_text)
    except Exception as e:
        logger.error(f"AI書評生成エラー {isbn}: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

    if result is None:
        return {"ok": False, "reason": "情報不足またはconfidence不足"}

    validation = validate_review(title, genre, result["review"])
    if not validation["passed"]:
        logger.warning(f"AI書評品質チェックNG {isbn}: {validation['errors']}")
        return {"ok": False, "reason": f"品質チェックNG: {'; '.join(validation['errors'])}"}
    if validation["warnings"]:
        logger.info(f"AI書評品質チェック警告 {isbn}: {validation['warnings']}")

    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        today = datetime.date.today().isoformat()
        tags_json = json.dumps(result["tags"], ensure_ascii=False)
        execute(
            con,
            f"""UPDATE genre_books
                SET description={ph}, ai_review_date={ph}, ai_review_score={ph},
                    ai_review_confidence={ph}, ai_model={ph}, ai_summary={ph}, ai_tags={ph}
                WHERE isbn={ph}""",
            (result["review"], today, result["score"], result.get("confidence"),
             MODEL, result["summary"], tags_json, isbn),
        )
        con.commit()
        return {"ok": True}
    except Exception as e:
        logger.error(f"AI書評DB保存エラー {isbn}: {e}", exc_info=True)
        try:
            con.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    finally:
        con.close()


def _fetch_regeneration_targets(limit: int, min_len: int = _MIN_LEN_DEFAULT) -> list[dict]:
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        rows = fetchall(
            con,
            f"""SELECT isbn, title, author, publisher, genre, description, awards
                FROM genre_books
                WHERE (manual_review IS NULL OR manual_review = {"FALSE" if USE_PG else "0"})
                  AND (description IS NULL OR LENGTH(description) < {ph})
                ORDER BY isbn
                LIMIT {ph}""",
            (min_len, limit),
        )
        return rows
    finally:
        con.close()


def estimate_regeneration(limit: int = _JOB_MAX_LIMIT) -> dict:
    """未生成（description NULL or 短い）対象件数と概算コストを返す。
    OpenAI APIは呼び出さない（無料の見積りのみ）。"""
    limit = min(limit, _JOB_MAX_LIMIT)
    targets = _fetch_regeneration_targets(limit)
    count = len(targets)
    input_tokens = count * _EST_INPUT_TOKENS_PER_BOOK
    output_tokens = count * _EST_OUTPUT_TOKENS_PER_BOOK
    cost_usd = (input_tokens / 1_000_000 * _PRICE_PER_1M_INPUT_USD
                + output_tokens / 1_000_000 * _PRICE_PER_1M_OUTPUT_USD)
    return {
        "target_count": count,
        "job_limit": limit,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(cost_usd, 4),
        "estimated_cost_jpy": round(cost_usd * _USD_TO_JPY),
        "note": "概算値です。実際の料金はOpenAI公式の最新料金・実際のトークン数により変動します。",
    }


def confidence_distribution() -> dict:
    """ai_review_confidenceが保存されている本の分布・平均・min/maxを返す。

    2026-07-11: 35冊検証で「confidenceの分布を見たい」という要望に応えられ
    なかった反省から、ai_review_confidence列の保存と合わせて追加した集計。
    """
    con = get_con()
    try:
        rows = fetchall(
            con,
            "SELECT ai_review_confidence FROM genre_books WHERE ai_review_confidence IS NOT NULL",
        )
    finally:
        con.close()

    values = [r["ai_review_confidence"] for r in rows if r.get("ai_review_confidence") is not None]
    total = len(values)
    if total == 0:
        return {
            "total_count": 0, "average": None, "min": None, "max": None,
            "buckets": {"60-64": 0, "65-69": 0, "70-79": 0, "80-89": 0, "90-100": 0},
        }

    buckets = {"60-64": 0, "65-69": 0, "70-79": 0, "80-89": 0, "90-100": 0}
    for v in values:
        if v < 65:
            buckets["60-64"] += 1
        elif v < 70:
            buckets["65-69"] += 1
        elif v < 80:
            buckets["70-79"] += 1
        elif v < 90:
            buckets["80-89"] += 1
        else:
            buckets["90-100"] += 1

    return {
        "total_count": total,
        "average": round(sum(values) / total, 1),
        "min": min(values),
        "max": max(values),
        "buckets": buckets,
    }


_regen_running = False
_regen_last_result = None


def is_regeneration_running() -> bool:
    return _regen_running


def get_regeneration_last_result():
    return _regen_last_result


def _fetch_book(isbn: str) -> dict | None:
    con = get_con()
    try:
        ph = "%s" if USE_PG else "?"
        return fetchone(con, f"SELECT isbn, title, author, publisher, genre, description, awards FROM genre_books WHERE isbn={ph}", (isbn,))
    finally:
        con.close()


def start_regeneration(limit: int, operator: str, isbn: str = "", isbns: list | None = None):
    """管理画面からの半自動再生成を開始する（Phase 1: 手動起動・件数上限あり）。

    isbn/isbnsを指定した場合、その書籍だけを対象に強制再生成する（未生成分の
    条件を無視する）。プロンプト改善の検証用の内部オプションでUIには露出しない。"""
    global _regen_running, _regen_last_result

    if not OPENAI_API_KEY:
        return {"error": "レビュー生成用APIキーが設定されていません"}, 400

    if _regen_running:
        return {"error": "既に実行中です"}, 409

    limit = min(int(limit or _JOB_MAX_LIMIT), _JOB_MAX_LIMIT)

    target_isbns = list(isbns) if isbns else ([isbn] if isbn else [])
    target_isbns = target_isbns[:_JOB_MAX_LIMIT]

    def _run():
        global _regen_running, _regen_last_result
        _regen_running = True
        try:
            if target_isbns:
                targets = [b for b in (_fetch_book(i) for i in target_isbns) if b]
            else:
                targets = _fetch_regeneration_targets(limit)
            success = 0
            skipped = 0
            errors = []
            for book in targets:
                book_isbn = book["isbn"]
                result = regenerate_one(book_isbn, book)
                if result.get("ok"):
                    success += 1
                elif result.get("reason"):
                    skipped += 1
                else:
                    errors.append({"isbn": book_isbn, "error": result.get("error")})
                time.sleep(0.5)
            _regen_last_result = {
                "target_count": len(targets),
                "success": success,
                "skipped": skipped,
                "errors": errors,
                "operator": operator,
            }
            logger.info(f"AI書評再生成: {success}/{len(targets)}件成功、スキップ{skipped}件、エラー{len(errors)}件")
        except Exception as e:
            logger.error(f"AI書評再生成エラー: {e}", exc_info=True)
            _regen_last_result = {"error": str(e)}
        finally:
            _regen_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "limit": limit}, 200

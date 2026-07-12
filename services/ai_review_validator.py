"""AI書評の生成後品質チェック（Validation Gate）。

2026-07-12: 「風姿花伝」（世阿弥の能楽論）が「馬場あき子によるミステリ・推理小説」
という完全な虚偽内容で生成された事故を受けて、生成前のプロンプト改善（コンテキスト
強化・confidence足切り）に加えて、生成後にも機械的な安全装置を設ける。

confidenceはAIの自己申告（生成前のリスク指標）であり、高confidenceでも誤り、
低confidenceでも正しいことがあるため、生成後に独立した検証を行う。

現時点では「絶対に誤りとは言い切れないが強く疑わしい」パターンのみをerrorsとして
検出する（false positiveで正しいレビューを握りつぶすリスクの方が大きいため、
検出範囲は保守的に絞る）。
"""
from __future__ import annotations

# ジャンルを強く断定する言い回し → その言い回しが示唆するジャンル。
# genre_books.genre と矛盾する場合のみエラーとする（風姿花伝クラスの事故を機械検出する）。
_GENRE_ASSERTION_PATTERNS: list[tuple[str, str]] = [
    ("ミステリ小説として", "ミステリ・推理"),
    ("推理小説の傑作", "ミステリ・推理"),
    ("本格ミステリ", "ミステリ・推理"),
    ("恋愛小説として", "恋愛・青春"),
    ("ラブストーリー", "恋愛・青春"),
    ("ホラー小説として", "ホラー・怪談"),
    ("怪談集として", "ホラー・怪談"),
    ("絵本として", "絵本・児童書"),
    ("SF小説として", "ファンタジー・SF"),
    ("ファンタジー小説として", "ファンタジー・SF"),
]

# 実際の分類がこれらのいずれかであれば、上記アサーションと矛盾しないとみなす
# （例: 「時代小説・歴史小説」の本が「ミステリ要素もある」と書かれても許容する必要はないが、
#  ジャンル体系の粒度の粗さによる誤検出を避けるための緩和リスト）
_GENRE_COMPATIBLE: dict[str, set[str]] = {
    "ミステリ・推理": {"ミステリ・推理"},
    "恋愛・青春": {"恋愛・青春"},
    "ホラー・怪談": {"ホラー・怪談"},
    "絵本・児童書": {"絵本・児童書", "児童文学"},
    "ファンタジー・SF": {"ファンタジー・SF"},
}

_MIN_REVIEW_LENGTH = 40
_MAX_REVIEW_LENGTH_WARN = 2500


def validate_review(title: str, genre: str, review_text: str) -> dict:
    """生成された書評本文を検証する。

    戻り値: {"passed": bool, "errors": [str, ...], "warnings": [str, ...]}
    errors が1件でもあれば保存を見送るべき（呼び出し側でreason付きdiscardする）。
    warnings は保存はするが、管理画面での目視確認候補として残す。
    """
    errors: list[str] = []
    warnings: list[str] = []
    text = review_text or ""

    if len(text) < _MIN_REVIEW_LENGTH:
        errors.append(f"レビュー本文が短すぎます（{len(text)}文字）")

    if len(text) > _MAX_REVIEW_LENGTH_WARN:
        warnings.append(f"レビュー本文が長すぎる可能性があります（{len(text)}文字）")

    current_genre = genre or ""
    for phrase, asserted_genre in _GENRE_ASSERTION_PATTERNS:
        if phrase in text:
            compatible = _GENRE_COMPATIBLE.get(asserted_genre, {asserted_genre})
            if current_genre and current_genre not in compatible:
                errors.append(
                    f"ジャンル不整合の疑い: 本文は「{phrase}」と記述しているが、"
                    f"登録ジャンルは「{current_genre}」"
                )

    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}


# confidenceのグレーゾーン（60〜74）は無条件で「medium」とし、75以上でも
# Validation警告があれば「medium」に格下げする。confidence未評価（None）は
# 判定材料がないため安全側で「medium」扱いとする。
_CONFIDENCE_LOW_MAX = 59
_CONFIDENCE_GRAY_MAX = 74


def compute_quality_tier(confidence: int | None, warning_count: int) -> str:
    """confidence（AI自己申告値）とValidation警告件数を組み合わせた総合品質ティアを返す。

    "high": そのまま採用して問題ない
    "medium": 要確認（管理画面での目視確認・将来の一括再生成候補）
    "low": 原則破棄・再生成対象（confidence 60未満はcall_openai_review側で
           既に生成破棄されるため、主に移行前の既存データ向けの分類）
    """
    if confidence is None:
        return "medium"
    if confidence <= _CONFIDENCE_LOW_MAX:
        return "low"
    if confidence <= _CONFIDENCE_GRAY_MAX:
        return "medium"
    if warning_count > 0:
        return "medium"
    return "high"

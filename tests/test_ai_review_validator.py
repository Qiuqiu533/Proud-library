"""
services.ai_review_validator の回帰テスト。
2026-07-12: AI書評品質改善Phase 2-1。生成前のプロンプト改善・confidence足切りに
加え、生成後にも機械的な安全装置（Validation Gate）を設けるために追加。
「風姿花伝」がミステリ・推理として誤生成された事故のクラスを機械検出できることを検証する。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.ai_review_validator import validate_review


def test_validate_review_passes_normal_review():
    result = validate_review("風姿花伝", "エッセイ・評論", "世阿弥が能楽の理念を説いた芸術論の古典として知られる作品です。" * 2)
    assert result["passed"] is True
    assert result["errors"] == []


def test_validate_review_detects_genre_assertion_mismatch():
    """風姿花伝クラスの事故（能楽の古典なのに「ミステリ小説として」と誤記述）を検出する。"""
    text = "本作はミステリ小説として、巧妙な謎解きが楽しめる一冊です。" * 2
    result = validate_review("風姿花伝", "エッセイ・評論", text)
    assert result["passed"] is False
    assert any("ジャンル不整合" in e for e in result["errors"])


def test_validate_review_allows_matching_genre_assertion():
    text = "本作はミステリ小説として、巧妙な謎解きが楽しめる一冊です。" * 2
    result = validate_review("○○事件", "ミステリ・推理", text)
    assert result["passed"] is True


def test_validate_review_rejects_too_short_text():
    result = validate_review("テスト本", "エッセイ・評論", "短い")
    assert result["passed"] is False
    assert any("短すぎ" in e for e in result["errors"])


def test_validate_review_warns_on_too_long_text():
    long_text = "あ" * 2600
    result = validate_review("テスト本", "エッセイ・評論", long_text)
    assert result["passed"] is True
    assert any("長すぎる" in w for w in result["warnings"])

from __future__ import annotations

from lint_note import mixed_language_issues
from lint_note_final_v2 import visible_prose


def test_evidence_anchor_does_not_trigger_mixed_language_false_positive() -> None:
    text = (
        "---\ntitle: Test\n---\n"
        "湿度高于 50%，线宽约 60 nm，激励为 18 V 与 150 kHz。"
        "（主文 p. 8，Methods）\n"
    )

    prose = visible_prose(text)

    assert "Methods" not in prose
    assert mixed_language_issues(prose) == []

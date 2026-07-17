from __future__ import annotations

from figure_artifact_gate_v2 import finalize_figure_decisions
from lint_note_final_v2 import visible_prose


def test_visible_prose_removes_parenthesized_and_display_tex() -> None:
    text = (
        "---\ntitle: Test\n---\n"
        "\u4e2d\u6587 \\(g=0.47\\pm0.01\\,\\mathrm{mK}\\) \u7ed3\u8bba\u3002\n"
        "\\[R \\propto T^{-1}\\]\n"
    )

    prose = visible_prose(text)

    assert "mathrm" not in prose
    assert "propto" not in prose
    assert "中文" in prose


def test_figure_artifact_gate_accepts_canonical_v2_pass_status() -> None:
    paper_id = "doi:10.0000/example"
    run_id = "run-v2"
    manifest = {
        "schema_version": "2.0",
        "artifact_type": "figure_manifest",
        "paper_id": paper_id,
        "run_id": run_id,
        "status": "pass",
        "failures": [],
        "assets": [],
    }
    decisions = {
        "schema_version": "2.0",
        "artifact_type": "figure_decisions",
        "paper_id": paper_id,
        "run_id": run_id,
        "status": "pass",
        "failures": [],
        "decisions": [
            {
                "target_id": "target-1",
                "figure_label": "Fig. 1",
                "decision": "omitted",
                "decision_reason": "not_needed_for_reader",
            }
        ],
    }

    result = finalize_figure_decisions(decisions, manifest_record=manifest)

    assert result["status"] == "pass"
    assert result["failures"] == []

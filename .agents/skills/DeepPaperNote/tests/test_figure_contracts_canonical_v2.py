from __future__ import annotations

from figure_contracts_v2 import normalize_figure_decisions


def _planner_record(*, reason: str, outcome: str = "placeholder") -> dict:
    return {
        "figure_decisions": {
            "schema_version": "2.0",
            "paper_id": "paper-test",
            "run_id": "run-test",
            "status": "ok",
            "failures": [],
            "decisions": [
                {
                    "target_id": "main|fig 1",
                    "display_label": "Fig. 1",
                    "decision": outcome,
                    "selected_asset_id": "",
                    "candidate_asset_ids": [],
                    "rejected_asset_ids": [],
                    "decision_reason": reason,
                }
            ],
        }
    }


def test_canonical_decision_artifact_uses_repository_status_enum() -> None:
    artifact = normalize_figure_decisions(
        _planner_record(reason="no_visually_usable_matching_asset"),
        require_final=True,
    )

    assert artifact["schema_version"] == "2.0"
    assert artifact["artifact_type"] == "figure_decisions"
    assert artifact["status"] == "pass"
    assert artifact["failures"] == []


def test_pending_semantic_review_cannot_pass_publish_gate() -> None:
    artifact = normalize_figure_decisions(
        _planner_record(reason="awaiting_semantic_confirmation"),
        require_final=True,
    )

    assert artifact["status"] == "fail"
    assert "figure_decision_0_semantic_review_pending" in artifact["failures"]


def test_explicit_omission_with_reason_is_a_valid_final_decision() -> None:
    artifact = normalize_figure_decisions(
        _planner_record(reason="not_material_to_the_note", outcome="omitted"),
        require_final=True,
    )

    assert artifact["status"] == "pass"

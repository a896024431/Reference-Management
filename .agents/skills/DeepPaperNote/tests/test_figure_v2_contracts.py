from __future__ import annotations

from pathlib import Path

import pytest
from figure_contracts import (
    FigureContractError,
    build_figure_asset_identity,
    figure_note_alignment_issues,
    make_figure_manifest,
    materialize_inserted_assets,
    render_figure_decision_block,
    sha256_bytes,
    validate_figure_decisions,
    validate_figure_manifest,
)
from figure_contracts_v2 import normalize_figure_decisions


def _asset(source: Path, *, quality: str = "usable") -> dict:
    content = source.read_bytes()
    digest = sha256_bytes(content)
    asset_id, filename, bbox_hash = build_figure_asset_identity(
        document_id="main",
        page_number=3,
        label="Fig. 2",
        bbox=[40.0, 80.0, 520.0, 360.0],
        content_sha256=digest,
    )
    return {
        "asset_id": asset_id,
        "document_id": "main",
        "page_number": 3,
        "label": "Fig. 2",
        "caption_text": "Fig. 2. Device geometry and transport measurement.",
        "filename": filename,
        "path": str(source),
        "ext": "png",
        "width": 800,
        "height": 480,
        "bbox_pt": [40.0, 80.0, 520.0, 360.0],
        "bbox_sha256": bbox_hash,
        "file_sha256": digest,
        "size_bytes": len(content),
        "extraction_level": "figure",
        "quality_signals": {
            "visual_quality_status": quality,
            "quality_reason_codes": [] if quality == "usable" else ["caption_only_suspected"],
        },
    }


def _decisions(asset_id: str, *, outcome: str = "inserted") -> dict:
    return {
        "schema_version": "2.0",
        "paper_id": "paper-test",
        "run_id": "run-test",
        "status": "ok",
        "failures": [],
        "decisions": [
            {
                "target_id": "main|fig 2",
                "display_label": "Fig. 2",
                "target_section": "实验体系与测量",
                "reason": "核对器件几何与测量链。",
                "decision": outcome,
                "selected_asset_id": asset_id if outcome == "inserted" else "",
                "candidate_asset_ids": [asset_id],
                "rejected_asset_ids": [],
            }
        ],
    }


def test_manifest_to_materialize_round_trip_is_hash_verified(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    manifest = make_figure_manifest(paper_id="paper-test", run_id="run-test", assets=[asset])
    decisions = _decisions(asset["asset_id"])

    assert validate_figure_manifest(manifest, verify_files=True) == []
    assert validate_figure_decisions(decisions, manifest=manifest) == []

    destination = tmp_path / "note" / "images"
    materialized = materialize_inserted_assets(
        manifest=manifest,
        decisions=decisions,
        destination_dir=destination,
    )

    assert len(materialized) == 1
    copied = destination / asset["filename"]
    assert copied.read_bytes() == source.read_bytes()
    note = f"![[Research/Test/images/{asset['filename']}]]"
    assert figure_note_alignment_issues(note, decisions, materialized=materialized) == []


def test_materialization_rejects_manifest_hash_drift(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"original")
    asset = _asset(source)
    manifest = make_figure_manifest(paper_id="paper-test", run_id="run-test", assets=[asset])
    decisions = _decisions(asset["asset_id"])
    source.write_bytes(b"changed-after-manifest")

    with pytest.raises(FigureContractError, match="source_hash_mismatch"):
        materialize_inserted_assets(
            manifest=manifest,
            decisions=decisions,
            destination_dir=tmp_path / "images",
        )


def test_rejected_candidate_cannot_be_selected(tmp_path: Path) -> None:
    source = tmp_path / "reject.png"
    source.write_bytes(b"caption-only")
    asset = _asset(source, quality="reject")
    manifest = make_figure_manifest(paper_id="paper-test", run_id="run-test", assets=[asset])
    decisions = _decisions(asset["asset_id"])
    decisions["decisions"][0]["rejected_asset_ids"] = [asset["asset_id"]]

    issues = validate_figure_decisions(decisions, manifest=manifest)

    assert "figure_decision_0_selected_asset_rejected" in issues
    assert "figure_decision_0_selected_asset_not_usable" in issues


def test_duplicate_labels_receive_distinct_ids_and_filenames() -> None:
    first = build_figure_asset_identity(
        document_id="main",
        page_number=4,
        label="Fig. 4",
        bbox=[10.0, 20.0, 200.0, 220.0],
        content_sha256="a" * 64,
    )
    second = build_figure_asset_identity(
        document_id="main",
        page_number=4,
        label="Fig. 4",
        bbox=[240.0, 20.0, 430.0, 220.0],
        content_sha256="b" * 64,
    )

    assert first[0] != second[0]
    assert first[1] != second[1]


def test_figure_rendering_keeps_planning_metadata_out_of_notes(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    inserted = _decisions(asset["asset_id"])

    rendered = render_figure_decision_block(inserted["decisions"][0], embed="![[images/fig-2.png]]")

    assert rendered.startswith("![[images/fig-2.png]]")
    assert "[!figure]" not in rendered
    assert "建议位置" not in rendered
    assert "放置原因" not in rendered
    assert "当前状态" not in rendered
    assert "图号身份" not in rendered


def test_placeholder_decision_is_run_only_and_needs_no_visible_callout(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    placeholder = _decisions(asset["asset_id"], outcome="placeholder")
    note = "正文自然引用 Fig. 2 来说明器件几何。"

    assert render_figure_decision_block(placeholder["decisions"][0]) == ""
    assert figure_note_alignment_issues(note, placeholder) == []

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

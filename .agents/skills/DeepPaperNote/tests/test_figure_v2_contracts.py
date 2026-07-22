from __future__ import annotations

from pathlib import Path

import pytest
from contracts_v2 import ContractError, artifact_header
from figure_contracts_v2 import (
    FigureContractError,
    build_figure_asset_identity,
    figure_note_alignment_issues,
    finalize_note_figure_decisions,
    make_figure_decisions,
    make_figure_manifest,
    materialize_decision,
    normalize_figure_decisions,
    normalize_figure_manifest,
    sha256_bytes,
    validate_figure_decisions,
    validate_figure_manifest,
)
from publish_note_v2 import validate_figure_sources


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
    return make_figure_decisions(
        paper_id="paper-test",
        run_id="run-test",
        decisions=[
            {
                "target_id": "main|fig 2",
                "display_label": "Fig. 2",
                "target_section": "实验体系与测量",
                "reason": "核对器件几何与测量链。",
                "decision": outcome,
                "selected_asset_id": asset_id if outcome == "inserted" else "",
                "candidate_asset_ids": [asset_id],
                "rejected_asset_ids": [],
                "decision_reason": "embedded_in_note" if outcome == "inserted" else "not_embedded",
            }
        ],
    )


def _manifest(asset: dict) -> dict:
    return make_figure_manifest(
        paper_id="paper-test",
        run_id="run-test",
        assets=[asset],
    )


def test_manifest_to_materialize_round_trip_is_hash_verified(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    manifest = _manifest(asset)
    decisions = _decisions(asset["asset_id"])

    assert validate_figure_manifest(manifest, verify_files=True) == []
    assert validate_figure_decisions(decisions, manifest=manifest) == []

    destination = tmp_path / "note" / "images"
    materialized = [
        materialize_decision(
            manifest=manifest,
            decisions=decisions,
            target_id="main|fig 2",
            destination_dir=destination,
        )
    ]

    assert len(materialized) == 1
    copied = destination / asset["filename"]
    assert copied.read_bytes() == source.read_bytes()
    note = f"![[文献/QPC/Test/images/{asset['filename']}]]"
    assert figure_note_alignment_issues(note, decisions, materialized=materialized) == []


def test_embedded_filename_finalizer_selects_only_current_manifest_assets(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    manifest = _manifest(asset)
    provisional = _decisions(asset["asset_id"], outcome="omitted")

    finalized = finalize_note_figure_decisions(
        manifest=manifest,
        provisional_decisions=provisional,
        embedded_filenames=[asset["filename"]],
    )

    decision = finalized["decisions"][0]
    assert finalized["status"] == "pass"
    assert decision["decision"] == "inserted"
    assert decision["selected_asset_id"] == asset["asset_id"]
    assert decision["decision_reason"] == "embedded_in_note"

    with pytest.raises(FigureContractError, match="current-run manifest"):
        finalize_note_figure_decisions(
            manifest=manifest,
            provisional_decisions=provisional,
            embedded_filenames=["old-or-misspelled.png"],
        )


def test_manifest_identity_and_paper_document_provenance_are_recomputed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    drifted = dict(asset)
    drifted["document_id"] = "ghost"
    drifted["page_number"] = 999

    normalized = normalize_figure_manifest(_manifest(drifted))
    assert normalized["status"] == "fail"
    assert any("asset_id_identity_mismatch" in failure for failure in normalized["failures"])

    record = artifact_header("paper_record", paper_id="paper-test", run_id="run-test")
    record["paper_record"] = {
        "paper_id": "paper-test",
        "metadata": {"title": "Paper Test"},
        "documents": [
            {
                "document_id": "main",
                "role": "main",
                "path": str(tmp_path / "paper.pdf"),
                "sha256": "0" * 64,
                "pages": 3,
            }
        ],
    }
    validate_figure_sources(_manifest(asset), record)

    page_four = dict(asset)
    page_four_id, page_four_filename, page_four_bbox_hash = build_figure_asset_identity(
        document_id="main",
        page_number=4,
        label=page_four["label"],
        bbox=page_four["bbox_pt"],
        content_sha256=page_four["file_sha256"],
    )
    page_four.update(
        {
            "asset_id": page_four_id,
            "filename": page_four_filename,
            "bbox_sha256": page_four_bbox_hash,
            "page_number": 4,
        }
    )
    with pytest.raises(ContractError, match="page is outside"):
        validate_figure_sources(_manifest(page_four), record)


def test_materialization_rejects_manifest_hash_drift(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"original")
    asset = _asset(source)
    manifest = _manifest(asset)
    decisions = _decisions(asset["asset_id"])
    source.write_bytes(b"changed-after-manifest")

    with pytest.raises(FigureContractError, match="source_hash_mismatch"):
        materialize_decision(
            manifest=manifest,
            decisions=decisions,
            target_id="main|fig 2",
            destination_dir=tmp_path / "images",
        )


def test_rejected_candidate_cannot_be_selected(tmp_path: Path) -> None:
    source = tmp_path / "reject.png"
    source.write_bytes(b"caption-only")
    asset = _asset(source, quality="reject")
    manifest = _manifest(asset)
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


def test_placeholder_decision_is_run_only_and_needs_no_visible_callout(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    placeholder = _decisions(asset["asset_id"], outcome="placeholder")
    note = "正文自然引用 Fig. 2 来说明器件几何。"

    assert figure_note_alignment_issues(note, placeholder) == []


def _planner_record(*, reason: str, outcome: str = "placeholder") -> dict:
    return {
        "figure_decisions": {
            "schema_version": "2.0",
            "artifact_type": "figure_decisions",
            "paper_id": "paper-test",
            "run_id": "run-test",
            "status": "pass",
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


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.png",
        "nested/escape.png",
        r"nested\escape.png",
        "fig..png",
        "figure.exe",
    ],
)
def test_manifest_rejects_unsafe_or_unsupported_filenames(
    tmp_path: Path, filename: str
) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    asset["filename"] = filename
    manifest = _manifest(asset)

    issues = validate_figure_manifest(manifest, verify_files=True)

    assert any("filename_" in issue for issue in issues)
    with pytest.raises(FigureContractError, match="filename"):
        materialize_decision(
            manifest=manifest,
            decisions=_decisions(asset["asset_id"]),
            target_id="main|fig 2",
            destination_dir=tmp_path / "note" / "images",
        )
    assert not (tmp_path / "note" / "escape.png").exists()


def test_manifest_rejects_absolute_filename(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"deterministic-png-fixture")
    asset = _asset(source)
    asset["filename"] = str((tmp_path / "escape.png").resolve())

    issues = validate_figure_manifest(_manifest(asset), verify_files=True)

    assert "figure_manifest_asset_0_filename_unsafe" in issues


def test_asset_identity_rejects_unsupported_extension() -> None:
    with pytest.raises(FigureContractError, match="Unsupported figure image extension"):
        build_figure_asset_identity(
            document_id="main",
            page_number=1,
            label="Fig. 1",
            bbox=[],
            extension="exe",
        )


@pytest.mark.parametrize("legacy_status", ["ok", "failed"])
def test_legacy_figure_statuses_are_rejected(legacy_status: str) -> None:
    manifest = make_figure_manifest(
        paper_id="paper-test",
        run_id="run-test",
        assets=[],
    )
    manifest["status"] = legacy_status

    normalized = normalize_figure_manifest(manifest)

    assert normalized["status"] == "fail"
    assert "figure_manifest_status_invalid" in normalized["failures"]

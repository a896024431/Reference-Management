from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import fitz
import pytest
from build_figure_contact_sheet_v2 import ContactSheetError, build_contact_sheet
from contracts_v2 import ContractError, canonical_json_sha256
from figure_contracts_v2 import (
    build_figure_asset_identity,
    make_figure_decisions,
    make_figure_manifest,
    sha256_file,
)
from figure_visual_review_contracts_v2 import (
    build_figure_visual_review,
    validate_figure_visual_review,
)
from publish_note_v2 import validate_visual_review_for_publish

PAPER_ID = "paper-contact-sheet-test"
RUN_ID = "run-contact-sheet-test"


def _make_png(path: Path, *, incomplete: bool = False) -> None:
    document = fitz.open()
    page = document.new_page(width=480, height=300)
    page.draw_rect(fitz.Rect(20, 30, 220, 250), color=(0.1, 0.3, 0.8), width=4)
    page.insert_text((35, 58), "A", fontsize=24)
    if not incomplete:
        page.draw_rect(fitz.Rect(260, 30, 460, 250), color=(0.8, 0.2, 0.1), width=4)
        page.insert_text((275, 58), "B", fontsize=24)
    page.get_pixmap(alpha=False).save(path)
    document.close()


def _asset(
    path: Path,
    *,
    quality: str = "usable",
    bbox: list[float] | None = None,
) -> dict:
    digest = sha256_file(path)
    crop = bbox or [20.0, 30.0, 460.0, 250.0]
    asset_id, filename, bbox_hash = build_figure_asset_identity(
        document_id="main",
        page_number=4,
        label="Fig. 2",
        bbox=crop,
        content_sha256=digest,
    )
    return {
        "asset_id": asset_id,
        "document_id": "main",
        "page_number": 4,
        "label": "Fig. 2",
        "caption_text": "Fig. 2. Combined panels A and B.",
        "filename": filename,
        "path": str(path),
        "ext": "png",
        "width": 480,
        "height": 300,
        "bbox_pt": crop,
        "bbox_sha256": bbox_hash,
        "file_sha256": digest,
        "size_bytes": path.stat().st_size,
        "extraction_level": "figure",
        "quality_signals": {
            "visual_quality_status": quality,
            "quality_reason_codes": [] if quality == "usable" else ["crop_incomplete"],
        },
    }


def _manifest(*assets: dict) -> dict:
    return make_figure_manifest(
        paper_id=PAPER_ID,
        run_id=RUN_ID,
        assets=assets,
    )


def _decisions(
    selected: str,
    *,
    candidate_ids: list[str] | None = None,
    rejected_ids: list[str] | None = None,
) -> dict:
    return make_figure_decisions(
        paper_id=PAPER_ID,
        run_id=RUN_ID,
        decisions=[
            {
                "target_id": "main|fig 2",
                "display_label": "Fig. 2",
                "decision": "inserted",
                "selected_asset_id": selected,
                "candidate_asset_ids": candidate_ids or [selected],
                "rejected_asset_ids": rejected_ids or [],
                "decision_reason": "identity and visual review required",
            }
        ],
    )


def _run_dir(tmp_path: Path) -> Path:
    path = tmp_path / ".local" / "deeppapernote" / "runs" / RUN_ID
    path.mkdir(parents=True)
    return path


def test_contact_sheet_rejects_a_vault_external_run_lookalike(tmp_path: Path) -> None:
    source = tmp_path / "figure.png"
    _make_png(source)
    asset = _asset(source)
    outside_run = (
        tmp_path / "outside" / ".local" / "deeppapernote" / "runs" / RUN_ID
    )
    outside_run.mkdir(parents=True)

    with pytest.raises(ContactSheetError, match="canonical"):
        build_contact_sheet(
            manifest=_manifest(asset),
            decisions=_decisions(asset["asset_id"]),
            run_dir=outside_run,
            vault_root=tmp_path,
        )


def _review(asset_id: str, **overrides: object) -> dict:
    item = {
        "asset_id": asset_id,
        "complete": True,
        "identity": True,
        "readable": True,
        "notes": "Both panels and labels are legible.",
    }
    item.update(overrides)
    return {"reviewer": "model-visual-review", "reviews": [item]}


def test_combination_candidates_are_grouped_and_sources_are_unchanged(tmp_path: Path) -> None:
    complete_path = tmp_path / "complete.png"
    rejected_path = tmp_path / "partial.png"
    _make_png(complete_path)
    _make_png(rejected_path, incomplete=True)
    complete = _asset(complete_path, quality="usable", bbox=[20, 30, 460, 250])
    rejected = _asset(rejected_path, quality="reject", bbox=[20, 30, 220, 250])
    manifest = _manifest(complete, rejected)
    decisions = _decisions(
        complete["asset_id"],
        candidate_ids=[complete["asset_id"]],
        rejected_ids=[rejected["asset_id"]],
    )
    before = {path: sha256_file(path) for path in (complete_path, rejected_path)}

    artifact = build_contact_sheet(
        manifest=manifest,
        decisions=decisions,
        run_dir=_run_dir(tmp_path),
        vault_root=tmp_path,
        columns=2,
        rows=1,
    )

    assert artifact["status"] == "pass"
    assert len(artifact["groups"]) == 1
    assert set(artifact["groups"][0]["asset_ids"]) == {complete["asset_id"]}
    cell_by_id = {cell["asset_id"]: cell for cell in artifact["cells"]}
    assert cell_by_id[complete["asset_id"]]["quality"] == "usable"
    assert "selected" in cell_by_id[complete["asset_id"]]["candidate_status"]
    assert rejected["asset_id"] not in cell_by_id
    sheet = Path(artifact["sheets"][0]["path"])
    assert artifact["sheets"][0]["sha256"] == sha256_file(sheet)
    with fitz.open(sheet) as rendered:
        assert rendered.page_count == 1
        assert rendered[0].rect.width == 1600
        assert rendered[0].rect.height == 1800
    assert {path: sha256_file(path) for path in before} == before


def test_incomplete_crop_cannot_pass_inserted_review(tmp_path: Path) -> None:
    source = tmp_path / "partial-but-heuristically-usable.png"
    _make_png(source, incomplete=True)
    asset = _asset(source, quality="usable")
    manifest = _manifest(asset)
    decisions = _decisions(asset["asset_id"])
    contact_sheet = build_contact_sheet(
        manifest=manifest,
        decisions=decisions,
        run_dir=_run_dir(tmp_path),
        vault_root=tmp_path,
    )

    review = build_figure_visual_review(
        manifest=manifest,
        decisions=decisions,
        contact_sheet=contact_sheet,
        review_source=_review(asset["asset_id"], complete=False),
    )

    assert review["status"] == "fail"
    assert f"figure_visual_review_{asset['asset_id']}_complete_false" in review["failures"]


def test_reject_cannot_be_overridden_to_inserted(tmp_path: Path) -> None:
    source = tmp_path / "rejected.png"
    _make_png(source, incomplete=True)
    asset = _asset(source, quality="reject")
    manifest = _manifest(asset)
    decisions = _decisions(
        asset["asset_id"],
        rejected_ids=[asset["asset_id"]],
    )
    contact_sheet = build_contact_sheet(
        manifest=manifest,
        decisions=decisions,
        run_dir=_run_dir(tmp_path),
        vault_root=tmp_path,
    )
    review_source = _review(asset["asset_id"], decision="inserted")

    review = build_figure_visual_review(
        manifest=manifest,
        decisions=decisions,
        contact_sheet=contact_sheet,
        review_source=review_source,
    )

    assert review["status"] == "fail"
    assert any("reject_override_forbidden" in failure for failure in review["failures"])
    assert any("selected_asset_not_usable" in failure for failure in review["failures"])
    assert any("selected_asset_rejected" in failure for failure in review["failures"])


def test_manifest_hash_mismatch_invalidates_review_and_publish_gate(tmp_path: Path) -> None:
    source = tmp_path / "complete.png"
    _make_png(source)
    asset = _asset(source)
    manifest = _manifest(asset)
    decisions = _decisions(asset["asset_id"])
    contact_sheet = build_contact_sheet(
        manifest=manifest,
        decisions=decisions,
        run_dir=_run_dir(tmp_path),
        vault_root=tmp_path,
    )
    review = build_figure_visual_review(
        manifest=manifest,
        decisions=decisions,
        contact_sheet=contact_sheet,
        review_source=_review(asset["asset_id"]),
    )
    assert review["status"] == "pass", review["failures"]
    validate_visual_review_for_publish(
        visual_review=review,
        contact_sheet=contact_sheet,
        artifacts={"figure_manifest": manifest, "figure_decisions": decisions},
    )

    changed_manifest = deepcopy(manifest)
    changed_manifest["assets"][0]["caption_text"] = "Fig. 2. Changed after review."
    with pytest.raises(ContractError, match="manifest hash mismatch"):
        validate_figure_visual_review(
            review,
            manifest=changed_manifest,
            decisions=decisions,
            contact_sheet=contact_sheet,
        )


def test_stale_decisions_contact_sheet_cannot_review_current_decisions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "complete.png"
    _make_png(source)
    asset = _asset(source)
    manifest = _manifest(asset)
    old_decisions = _decisions(asset["asset_id"])
    old_contact_sheet = build_contact_sheet(
        manifest=manifest,
        decisions=old_decisions,
        run_dir=_run_dir(tmp_path),
        vault_root=tmp_path,
    )
    current_decisions = deepcopy(old_decisions)
    current_decisions["decisions"][0]["decision_reason"] = "updated final rationale"

    rejected = build_figure_visual_review(
        manifest=manifest,
        decisions=current_decisions,
        contact_sheet=old_contact_sheet,
        review_source=_review(asset["asset_id"]),
    )
    assert rejected["status"] == "fail"
    assert (
        "figure_visual_review_contact_sheet_decisions_hash_mismatch"
        in rejected["failures"]
    )

    forged = build_figure_visual_review(
        manifest=manifest,
        decisions=old_decisions,
        contact_sheet=old_contact_sheet,
        review_source=_review(asset["asset_id"]),
    )
    forged["decisions_sha256"] = canonical_json_sha256(current_decisions)
    with pytest.raises(ContractError, match="Contact-sheet decisions hash mismatch"):
        validate_figure_visual_review(
            forged,
            manifest=manifest,
            decisions=current_decisions,
            contact_sheet=old_contact_sheet,
        )


def test_no_embedded_figure_needs_no_contact_sheet_or_visual_review() -> None:
    manifest = _manifest()
    decisions = make_figure_decisions(
        paper_id=PAPER_ID,
        run_id=RUN_ID,
        decisions=[],
    )

    validate_visual_review_for_publish(
        visual_review=None,
        contact_sheet=None,
        artifacts={"figure_manifest": manifest, "figure_decisions": decisions},
    )

    with pytest.raises(ContractError, match="No embedded image"):
        validate_visual_review_for_publish(
            visual_review={"unexpected": True},
            contact_sheet=None,
            artifacts={"figure_manifest": manifest, "figure_decisions": decisions},
        )

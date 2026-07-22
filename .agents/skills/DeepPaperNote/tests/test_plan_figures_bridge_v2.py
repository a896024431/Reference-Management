from __future__ import annotations

from contracts_v2 import artifact_header
from figure_contracts_v2 import make_figure_manifest
from plan_figures_v2 import build_release_figure_plan_artifact

PAPER_ID = "paper-release-bridge"
RUN_ID = "run-release-bridge"


def _asset(
    asset_id: str,
    *,
    document_id: str = "doc-main",
    page: int = 2,
    label: str = "Figure 1",
    caption: str = "Figure 1. Device geometry and measurement wiring.",
    quality: str = "usable",
    detection: str = "anchored_label_v2",
) -> dict:
    return {
        "asset_id": asset_id,
        "document_id": document_id,
        "page_number": page,
        "label": label,
        "caption_text": caption,
        "caption_detection": detection,
        "filename": f"{asset_id}.png",
        "path": f"/tmp/{asset_id}.png",
        "file_sha256": "a" * 64,
        "width": 900,
        "height": 500,
        "size_bytes": 4096,
        "extraction_level": "figure",
        "identity_confidence": 1.0,
        "quality_signals": {
            "visual_quality_status": quality,
            "quality_reason_codes": ([] if quality == "usable" else ["caption_only_suspected"]),
            "visual_body_ratio": 0.6 if quality == "usable" else 0.01,
            "page_coverage_ratio": 0.3,
        },
    }


def _evidence(figure_captions: list[dict] | None = None) -> dict:
    artifact = artifact_header(
        "evidence_pack",
        paper_id=PAPER_ID,
        run_id=RUN_ID,
        status="pass",
    )
    artifact["evidence_pack"] = {
        "figure_captions": figure_captions or [],
        "table_captions": [],
    }
    return artifact


def _assets(entries: list[dict]) -> dict:
    manifest = make_figure_manifest(
        paper_id=PAPER_ID,
        run_id=RUN_ID,
        assets=entries,
        status="pass",
    )
    artifact = artifact_header(
        "pdf_assets",
        paper_id=PAPER_ID,
        run_id=RUN_ID,
        status="pass",
    )
    artifact.update(
        {
            "page_assets": [],
            "image_assets": [],
            "figure_manifest": manifest,
        }
    )
    return artifact


def test_empty_evidence_inventory_bridges_only_anchored_usable_caption() -> None:
    usable = _asset("usable-fig-1")
    rejected = _asset(
        "reject-fig-2",
        page=3,
        label="Figure 2",
        caption="Figure 2. Caption-only crop.",
        quality="reject",
    )
    body_reference = _asset(
        "body-reference-fig-3",
        page=4,
        label="Figure 3",
        caption="Figure 3 shows the measured conductance.",
    )

    artifact = build_release_figure_plan_artifact(
        _evidence(), _assets([usable, rejected, body_reference]), max_items=0
    )

    figures = artifact["figure_plan"]["figures"]
    decisions = artifact["figure_decisions"]["decisions"]
    assert artifact["status"] == "pass"
    assert artifact["caption_bridge"]["created"] == 1
    assert len(figures) == len(decisions) == 1
    assert figures[0]["source_asset_id"] == "usable-fig-1"
    assert decisions[0]["recommended_asset_id"] == "usable-fig-1"
    assert decisions[0]["selected_asset_id"] == ""
    assert decisions[0]["decision"] == "omitted"
    assert decisions[0]["decision_reason"] == "not_embedded"
    assert "reject-fig-2" not in decisions[0]["candidate_asset_ids"]
    assert "body-reference-fig-3" not in decisions[0]["candidate_asset_ids"]


def test_main_and_supplement_same_label_remain_separate() -> None:
    main = _asset("main-fig-1", document_id="doc-main", page=2)
    supplement = _asset(
        "supplement-fig-1",
        document_id="doc-si",
        page=3,
        caption="Figure 1. Supplement calibration sweep.",
    )

    artifact = build_release_figure_plan_artifact(
        _evidence(), _assets([main, supplement]), max_items=0
    )

    decisions = artifact["figure_decisions"]["decisions"]
    assert len(decisions) == 2
    assert len({item["target_id"] for item in decisions}) == 2
    by_document = {item["document_id"]: item for item in decisions}
    assert by_document["doc-main"]["candidate_asset_ids"] == ["main-fig-1"]
    assert by_document["doc-main"]["recommended_asset_id"] == "main-fig-1"
    assert by_document["doc-si"]["candidate_asset_ids"] == ["supplement-fig-1"]
    assert by_document["doc-si"]["recommended_asset_id"] == ("supplement-fig-1")


def test_existing_evidence_caption_is_not_duplicated_by_bridge() -> None:
    evidence = _evidence(
        [
            {
                "id": "Fig. 1",
                "caption": "Device geometry and measurement wiring.",
                "document_id": "doc-main",
                "page_number": 2,
            }
        ]
    )

    artifact = build_release_figure_plan_artifact(
        evidence, _assets([_asset("usable-fig-1")]), max_items=0
    )

    assert len(artifact["figure_plan"]["figures"]) == 1
    assert artifact["caption_bridge"]["created"] == 0
    assert artifact["caption_bridge"]["already_in_evidence"] == 1


def test_reject_or_non_anchored_manifest_cannot_create_target() -> None:
    rejected = _asset("reject", quality="reject")
    non_anchored = _asset(
        "body-reference",
        page=5,
        label="Figure 5",
        caption="Figure 5. Conductance trace discussed in text.",
        detection="body_reference_v2",
    )

    artifact = build_release_figure_plan_artifact(
        _evidence(), _assets([rejected, non_anchored]), max_items=0
    )

    assert artifact["status"] == "pass"
    assert artifact["caption_bridge"]["created"] == 0
    assert artifact["figure_plan"]["figures"] == []
    assert artifact["figure_decisions"]["decisions"] == []

from __future__ import annotations

from plan_figures_v2 import (
    attach_candidate_images,
    build_figure_decisions,
    build_figure_items,
    rank_matching_assets,
)


def _item(label: str = "Fig. 2") -> dict:
    return {
        "target_id": f"main|{label.lower()}",
        "id": label,
        "caption": "Device geometry and transport measurement setup.",
        "document_id": "main",
        "section": "实验体系与测量",
        "reason": "核对器件结构与测量链。",
        "priority": 1,
        "insert_mode": "placeholder",
    }


def _asset(asset_id: str, *, quality: str, caption: str, page: int = 3) -> dict:
    return {
        "asset_id": asset_id,
        "document_id": "main",
        "page_number": page,
        "label": "Figure 2",
        "caption_text": caption,
        "filename": f"{asset_id}.png",
        "path": f"/tmp/{asset_id}.png",
        "file_sha256": "a" * 64,
        "width": 800,
        "height": 420,
        "size_bytes": 2048,
        "extraction_level": "figure",
        "quality_signals": {
            "visual_quality_status": quality,
            "quality_reason_codes": [] if quality == "usable" else ["caption_only_suspected"],
            "visual_body_ratio": 0.30 if quality == "usable" else 0.01,
            "page_coverage_ratio": 0.25,
        },
    }


def test_first_reject_does_not_hide_later_usable_candidate() -> None:
    reject = _asset(
        "fig-reject",
        quality="reject",
        caption="Figure 2. Device geometry and transport measurement setup.",
    )
    usable = _asset(
        "fig-usable",
        quality="usable",
        caption="Figure 2. Device geometry and transport measurement setup.",
    )

    planned = attach_candidate_images(
        [_item()],
        page_assets=[
            {
                "document_id": "main",
                "page_number": 3,
                "page_text": "Figure 2. Device geometry and transport measurement setup.",
                "text_preview": "Figure 2.",
            }
        ],
        image_assets=[],
        figure_assets=[reject, usable],
    )

    assert planned[0]["figure_asset_candidate"]["asset_id"] == "fig-usable"
    assert planned[0]["recommended_asset_id"] == "fig-usable"
    assert planned[0]["rejected_asset_ids"] == ["fig-reject"]
    assert planned[0]["insert_mode"] == "placeholder"


def test_duplicate_label_candidates_are_ranked_by_caption_and_quality() -> None:
    weak = _asset(
        "fig-weak",
        quality="usable",
        caption="Figure 2. Unrelated calibration image.",
        page=2,
    )
    strong = _asset(
        "fig-strong",
        quality="usable",
        caption="Figure 2. Device geometry and transport measurement setup.",
        page=3,
    )

    ranked = rank_matching_assets(_item(), [weak, strong])

    assert [candidate["asset_id"] for candidate in ranked] == ["fig-strong", "fig-weak"]
    assert ranked[0]["caption_similarity"] > ranked[1]["caption_similarity"]


def test_planner_emits_placeholder_first_v2_decision_with_recommendation() -> None:
    usable = _asset(
        "fig-usable",
        quality="usable",
        caption="Figure 2. Device geometry and transport measurement setup.",
    )
    item = attach_candidate_images(
        [_item()], page_assets=[], image_assets=[], figure_assets=[usable]
    )[0]

    artifact = build_figure_decisions(paper_id="paper-test", run_id="run-test", items=[item])
    decision = artifact["decisions"][0]

    assert artifact["schema_version"] == "2.0"
    assert decision["decision"] == "placeholder"
    assert decision["selected_asset_id"] == ""
    assert decision["recommended_asset_id"] == "fig-usable"
    assert decision["candidate_asset_ids"] == ["fig-usable"]


def test_main_and_supplement_labels_do_not_collapse() -> None:
    evidence = {
        "figure_captions": [
            {"id": "Fig. 1", "caption": "Main result", "document_id": "main"},
            {"id": "Fig. 1", "caption": "Supplement control", "document_id": "supplement"},
            {"id": "Fig. S1", "caption": "Supplement sweep", "document_id": "supplement"},
        ]
    }

    items = build_figure_items(evidence, limit=0)

    assert len(items) == 3
    assert len({item["target_id"] for item in items}) == 3

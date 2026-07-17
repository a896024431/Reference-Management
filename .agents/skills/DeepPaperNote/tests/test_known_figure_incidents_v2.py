from __future__ import annotations

import pytest
from figure_contracts import build_figure_asset_identity
from plan_figures_v2 import attach_candidate_images


@pytest.mark.parametrize(
    ("incident", "page", "label"),
    [
        pytest.param("nanoscale_fig4", 5, "Fig. 4", id="nanoscale-fig4-overwrite"),
        pytest.param("hard_soft_fig2", 2, "Fig. 2", id="hard-soft-fig2-overwrite"),
        pytest.param("slow_quasiparticle_fig1", 2, "Fig. 1", id="slow-fig1-overwrite"),
    ],
)
def test_known_same_number_overwrite_incidents_keep_unique_assets(
    incident: str, page: int, label: str
) -> None:
    first = build_figure_asset_identity(
        document_id=f"main-{incident}",
        page_number=page,
        label=label,
        bbox=[30.0, 50.0, 270.0, 310.0],
        content_sha256="1" * 64,
    )
    second = build_figure_asset_identity(
        document_id=f"main-{incident}",
        page_number=page,
        label=label,
        bbox=[285.0, 50.0, 560.0, 310.0],
        content_sha256="2" * 64,
    )

    assert first[0] != second[0]
    assert first[1] != second[1]
    assert first[2] != second[2]


def _target(label: str, caption: str) -> dict:
    return {
        "target_id": f"main|{label.lower()}",
        "id": label,
        "caption": caption,
        "document_id": "main",
        "section": "主要结果与证据链",
        "reason": "核对关键实验结果。",
        "priority": 1,
        "insert_mode": "placeholder",
    }


def _candidate(asset_id: str, *, label: str, caption: str, quality: str) -> dict:
    return {
        "asset_id": asset_id,
        "document_id": "main",
        "page_number": 2,
        "label": label,
        "caption_text": caption,
        "filename": f"{asset_id}.png",
        "path": f"/tmp/{asset_id}.png",
        "file_sha256": ("a" if quality == "reject" else "b") * 64,
        "width": 900,
        "height": 520,
        "size_bytes": 4096,
        "extraction_level": "figure",
        "quality_signals": {
            "visual_quality_status": quality,
            "quality_reason_codes": [] if quality == "usable" else ["caption_only_suspected"],
            "visual_body_ratio": 0.55 if quality == "usable" else 0.01,
            "page_coverage_ratio": 0.30,
        },
    }


@pytest.mark.parametrize(
    ("case_id", "label", "caption"),
    [
        pytest.param(
            "hard-soft-fig2",
            "Fig. 2",
            "Hard and soft phase-slip regimes and representative traces.",
            id="hard-soft-reject-first",
        ),
        pytest.param(
            "slow-quasiparticle-fig1",
            "Fig. 1",
            "Interferometer geometry and slow quasiparticle switching.",
            id="slow-quasiparticle-reject-first",
        ),
    ],
)
def test_known_reject_first_incidents_choose_later_usable_candidate(
    case_id: str, label: str, caption: str
) -> None:
    rejected = _candidate(
        f"{case_id}-reject",
        label=label,
        caption=caption,
        quality="reject",
    )
    usable = _candidate(
        f"{case_id}-usable",
        label=label,
        caption=caption,
        quality="usable",
    )

    planned = attach_candidate_images(
        [_target(label, caption)],
        page_assets=[
            {
                "document_id": "main",
                "page_number": 2,
                "page_text": f"{label}. {caption}",
                "text_preview": label,
            }
        ],
        image_assets=[],
        figure_assets=[rejected, usable],
    )[0]

    assert planned["recommended_asset_id"] == usable["asset_id"]
    assert planned["figure_asset_candidate"]["asset_id"] == usable["asset_id"]
    assert planned["rejected_asset_ids"] == [rejected["asset_id"]]

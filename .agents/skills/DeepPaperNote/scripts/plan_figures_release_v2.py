#!/usr/bin/env python3
"""Final figure-planning entrypoint with a manifest-caption bridge.

The evidence extractor and the PDF asset extractor intentionally use different
parsers.  If evidence contains no caption inventory but the canonical manifest
contains visually usable, caption-anchored assets, this release planner creates
placeholder-first figure intents from those assets.  It never treats body
references or rejected crops as figure targets.
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

import plan_figures_v2 as core
from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    require_v2_artifact,
)
from extract_pdf_assets_v2 import _parse_caption_start
from figure_contracts_v2 import (
    normalize_figure_decisions,
    normalize_figure_label,
    normalize_figure_manifest,
)

BRIDGE_SOURCE = "manifest_caption_bridge_v2"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--evidence", required=True)
    command.add_argument("--assets", required=True)
    command.add_argument("--output", default="")
    command.add_argument("--max-items", type=int, default=0, help="0 keeps every target.")
    return command


def _quality_status(asset: dict[str, Any]) -> str:
    signals = asset.get("quality_signals", {})
    if not isinstance(signals, dict):
        return ""
    return str(signals.get("visual_quality_status", ""))


def _bridge_identity(
    asset: dict[str, Any],
) -> tuple[str, str, int] | None:
    """Return a stable bridge identity only for a real usable caption crop."""
    if str(asset.get("caption_detection", "")) != "anchored_label_v2":
        return None
    if _quality_status(asset) != "usable":
        return None
    document_id = str(asset.get("document_id", "")).strip()
    page_number = int(asset.get("page_number", 0) or 0)
    label = normalize_figure_label(str(asset.get("label", "")))
    if not document_id or page_number <= 0 or not label:
        return None
    if not label.startswith(("fig ", "fig s", "table ", "extended data fig ")):
        return None
    parsed = _parse_caption_start(str(asset.get("caption_text", "")))
    if parsed is None:
        return None
    if normalize_figure_label(parsed["label"]) != label:
        return None
    return document_id, label, page_number


def _bridge_rank(asset: dict[str, Any]) -> tuple[float, float, int, str]:
    signals = asset.get("quality_signals", {})
    if not isinstance(signals, dict):
        signals = {}
    return (
        float(asset.get("identity_confidence", 0.0) or 0.0),
        float(signals.get("visual_body_ratio", 0.0) or 0.0),
        len(str(asset.get("caption_text", ""))),
        str(asset.get("asset_id", "")),
    )


def build_manifest_caption_bridge_items(
    existing_items: list[dict[str, Any]],
    manifest_assets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build missing intents without collapsing main and supplement labels."""
    existing_labels = {
        (
            str(item.get("document_id", "") or "main"),
            normalize_figure_label(str(item.get("id", ""))),
        )
        for item in existing_items
    }
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    counters: Counter[str] = Counter()
    for raw in manifest_assets:
        if not isinstance(raw, dict):
            counters["non_object"] += 1
            continue
        identity = _bridge_identity(raw)
        if identity is None:
            if _quality_status(raw) != "usable":
                counters["not_usable"] += 1
            elif str(raw.get("caption_detection", "")) != "anchored_label_v2":
                counters["not_anchored"] += 1
            else:
                counters["caption_start_rejected"] += 1
            continue
        document_id, label, _ = identity
        if (document_id, label) in existing_labels:
            counters["already_in_evidence"] += 1
            continue
        grouped.setdefault(identity, []).append(raw)

    bridge_items: list[dict[str, Any]] = []
    for (document_id, label, page_number), candidates in grouped.items():
        source = max(candidates, key=_bridge_rank)
        display_label = str(source.get("label", ""))
        caption = str(source.get("caption_text", "")).strip()
        kind, section, reason, priority = core._classify_caption(display_label, caption)
        bridge_items.append(
            {
                "target_id": (f"{document_id}|{label}|p{page_number:04d}"),
                "id": display_label,
                "caption": caption,
                "document_id": document_id,
                "page_number": page_number,
                "kind": kind,
                "section": section,
                "reason": reason,
                "priority": priority,
                "anchor_text": section,
                "insert_mode": "placeholder",
                "intent_source": BRIDGE_SOURCE,
                "source_asset_id": str(source.get("asset_id", "")),
            }
        )
    bridge_items.sort(
        key=lambda item: (
            int(item["priority"]),
            str(item["document_id"]),
            int(item["page_number"]),
            normalize_figure_label(str(item["id"])),
        )
    )
    counters["created"] = len(bridge_items)
    return bridge_items, dict(counters)


def _stabilize_bridged_candidates(items: list[dict[str, Any]]) -> None:
    """Keep bridged recommendations on the source document and page."""
    for item in items:
        if item.get("intent_source") != BRIDGE_SOURCE:
            continue
        source_page = int(item.get("page_number", 0) or 0)
        candidates = [
            candidate
            for candidate in item.get("figure_asset_candidates", [])
            if int(candidate.get("page_number", 0) or 0) == source_page
        ]
        usable = [
            candidate
            for candidate in candidates
            if candidate.get("candidate_status") == "usable_candidate"
        ]
        rejected = [
            candidate
            for candidate in candidates
            if candidate.get("candidate_status") == "reject_visual_quality"
        ]
        item["figure_asset_candidates"] = candidates
        item["rejected_asset_ids"] = [str(candidate.get("asset_id", "")) for candidate in rejected]
        if usable:
            item["figure_asset_candidate"] = usable[0]
            item["recommended_asset_id"] = str(usable[0].get("asset_id", ""))
            item["candidate_status"] = "usable_candidate"
        else:
            item.pop("figure_asset_candidate", None)
            item["recommended_asset_id"] = ""
            item["candidate_status"] = "no_insertable_candidate"


def build_release_figure_plan_artifact(
    evidence_artifact: dict[str, Any],
    assets_artifact: dict[str, Any],
    *,
    max_items: int = 0,
) -> dict[str, Any]:
    require_v2_artifact(evidence_artifact, artifact_type="evidence_pack")
    require_v2_artifact(assets_artifact, artifact_type="pdf_assets")
    paper_id, run_id = require_same_identity(evidence_artifact, assets_artifact)
    manifest = normalize_figure_manifest(assets_artifact)
    pack = evidence_artifact.get("evidence_pack", {})
    if not isinstance(pack, dict):
        pack = {}
    evidence_items = core.build_figure_items(pack, limit=0)
    bridge_items, bridge_summary = build_manifest_caption_bridge_items(
        evidence_items,
        [asset for asset in manifest.get("assets", []) if isinstance(asset, dict)],
    )
    items = evidence_items + bridge_items
    items.sort(
        key=lambda item: (
            int(item.get("priority", 3) or 3),
            str(item.get("document_id", "")),
            int(item.get("page_number", 0) or 0),
            normalize_figure_label(str(item.get("id", ""))),
        )
    )
    if max_items > 0:
        items = items[:max_items]
    items = core.attach_candidate_images(
        items,
        assets_artifact.get("page_assets", []),
        assets_artifact.get("image_assets", []),
        manifest.get("assets", []),
    )
    _stabilize_bridged_candidates(items)
    raw_decisions = core.build_figure_decisions(paper_id=paper_id, run_id=run_id, items=items)
    has_pending = any(
        item.get("decision_reason") == "awaiting_semantic_confirmation"
        for item in raw_decisions.get("decisions", [])
        if isinstance(item, dict)
    )
    raw_decisions["status"] = "degraded" if has_pending else "ok"
    decisions = normalize_figure_decisions(raw_decisions, manifest=manifest, require_final=False)
    status = "degraded" if has_pending else "pass"
    artifact = artifact_header("figure_plan", paper_id=paper_id, run_id=run_id, status=status)
    artifact.update(
        {
            "planner": "plan_figures_release_v2.py",
            "figure_plan": {
                "paper_id": paper_id,
                "run_id": run_id,
                "figures": items,
            },
            "figure_manifest": manifest,
            "figure_decisions": decisions,
            "caption_bridge": {
                "source": BRIDGE_SOURCE,
                "evidence_targets": len(evidence_items),
                **bridge_summary,
            },
        }
    )
    return artifact


def main() -> None:
    args = parser().parse_args()
    artifact = build_release_figure_plan_artifact(
        load_json_object(args.evidence),
        load_json_object(args.assets),
        max_items=args.max_items,
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Canonical figure planning CLI for evidence_pack + pdf_assets v2."""

from __future__ import annotations

import argparse

from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    require_v2_artifact,
)
from figure_contracts_v2 import normalize_figure_decisions, normalize_figure_manifest
from plan_figures_v2 import attach_candidate_images, build_figure_decisions, build_figure_items


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "plan figures contract v2")
    p.add_argument("--evidence", required=True, help="evidence_pack v2 JSON.")
    p.add_argument("--assets", required=True, help="pdf_assets v2 JSON.")
    p.add_argument("--output", default="")
    p.add_argument("--max-items", type=int, default=12, help="0 keeps all items.")
    return p


def build_figure_plan_artifact(
    evidence_artifact: dict,
    assets_artifact: dict,
    *,
    max_items: int = 12,
) -> dict:
    require_v2_artifact(evidence_artifact, artifact_type="evidence_pack")
    require_v2_artifact(assets_artifact, artifact_type="pdf_assets")
    paper_id, run_id = require_same_identity(evidence_artifact, assets_artifact)
    manifest = normalize_figure_manifest(assets_artifact)
    items = build_figure_items(evidence_artifact.get("evidence_pack", {}), limit=max_items)
    items = attach_candidate_images(
        items,
        assets_artifact.get("page_assets", []),
        assets_artifact.get("image_assets", []),
        manifest.get("assets", []),
    )
    raw_decisions = build_figure_decisions(paper_id=paper_id, run_id=run_id, items=items)
    has_pending_review = any(
        decision.get("decision_reason") == "awaiting_semantic_confirmation"
        for decision in raw_decisions.get("decisions", [])
        if isinstance(decision, dict)
    )
    raw_decisions["status"] = "degraded" if has_pending_review else "ok"
    decisions = normalize_figure_decisions(raw_decisions, manifest=manifest, require_final=False)
    status = "degraded" if has_pending_review else "pass"
    artifact = artifact_header("figure_plan", paper_id=paper_id, run_id=run_id, status=status)
    artifact["figure_plan"] = {
        "paper_id": paper_id,
        "run_id": run_id,
        "figures": items,
    }
    artifact["figure_manifest"] = manifest
    artifact["figure_decisions"] = decisions
    return artifact


def main() -> None:
    args = parser().parse_args()
    evidence = load_json_object(args.evidence)
    assets = load_json_object(args.assets)
    artifact = build_figure_plan_artifact(evidence, assets, max_items=args.max_items)
    emit_json(artifact, args.output or None)


if __name__ == "__main__":
    main()

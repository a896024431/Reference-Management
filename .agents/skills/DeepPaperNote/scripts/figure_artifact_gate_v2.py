#!/usr/bin/env python3
"""Normalize and gate v2 figure artifacts before strict note publication."""

from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any

from common import emit, maybe_load_json_record
from figure_contracts_v2 import (
    SCHEMA_VERSION as FIGURE_SCHEMA_VERSION,
)
from figure_contracts_v2 import (
    validate_figure_decisions,
    validate_figure_manifest,
)


def coerce_figure_manifest(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    nested = record.get("figure_manifest")
    return deepcopy(nested if isinstance(nested, dict) else record)


def coerce_figure_decisions(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    nested = record.get("figure_decisions")
    return deepcopy(nested if isinstance(nested, dict) else record)


def normalize_manifest_artifact(record: dict[str, Any]) -> dict[str, Any]:
    manifest = coerce_figure_manifest(record)
    manifest["schema_version"] = manifest.get("schema_version") or FIGURE_SCHEMA_VERSION
    manifest["artifact_type"] = "figure_manifest"
    issues = validate_figure_manifest(manifest, verify_files=False)
    existing_failures = list(manifest.get("failures", []) or [])
    manifest["failures"] = sorted(set(existing_failures + issues))
    manifest["status"] = "pass" if not manifest["failures"] else "fail"
    return manifest


def finalize_figure_decisions(
    record: dict[str, Any],
    *,
    manifest_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a publication artifact whose status is pass only when final.

    Placeholder and omitted outcomes are valid final decisions.  A planner's
    ``awaiting_semantic_confirmation`` marker is not: the model must explicitly
    confirm the placeholder/omission or select a usable asset first.
    """
    decisions = coerce_figure_decisions(record)
    decisions["schema_version"] = decisions.get("schema_version") or FIGURE_SCHEMA_VERSION
    decisions["artifact_type"] = "figure_decisions"
    manifest = coerce_figure_manifest(manifest_record) if manifest_record else None
    contract_issues = validate_figure_decisions(decisions, manifest=manifest)
    review_issues: list[str] = []
    entries = decisions.get("decisions", [])
    if not isinstance(entries, list) or not entries:
        review_issues.append("figure_decisions_empty")
    else:
        for index, decision in enumerate(entries):
            if not isinstance(decision, dict):
                continue
            reason = str(decision.get("decision_reason", ""))
            outcome = str(decision.get("decision", ""))
            if reason == "awaiting_semantic_confirmation":
                review_issues.append(f"figure_decision_{index}_semantic_review_pending")
            if outcome == "omitted" and not reason:
                review_issues.append(f"figure_decision_{index}_omission_reason_missing")
            if outcome == "placeholder" and not reason:
                review_issues.append(f"figure_decision_{index}_placeholder_reason_missing")
    existing_failures = [
        failure
        for failure in (decisions.get("failures", []) or [])
        if failure not in {"awaiting_semantic_confirmation", "planner_output_not_final"}
    ]
    decisions["failures"] = sorted(set(existing_failures + contract_issues + review_issues))
    decisions["status"] = "pass" if not decisions["failures"] else "fail"
    return decisions


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "figure artifact gate v2")
    p.add_argument("--input", required=True, help="Direct or nested figure_decisions JSON.")
    p.add_argument("--manifest", default="", help="Direct or nested figure_manifest JSON.")
    p.add_argument("--output", default="")
    return p


def main() -> None:
    args = parser().parse_args()
    record = maybe_load_json_record(args.input)
    manifest = maybe_load_json_record(args.manifest) if args.manifest else None
    if not isinstance(record, dict):
        raise SystemExit("figure_artifact_gate_v2.py requires valid decisions JSON.")
    artifact = finalize_figure_decisions(record, manifest_record=manifest)
    emit(artifact, args.output)
    if artifact["status"] != "pass":
        raise SystemExit(
            "Figure decisions are not publication-ready: " + "; ".join(artifact["failures"])
        )


if __name__ == "__main__":
    main()

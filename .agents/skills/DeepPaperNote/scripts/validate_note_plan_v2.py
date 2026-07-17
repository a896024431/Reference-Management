#!/usr/bin/env python3
"""Validate a model-authored note plan against a v2 synthesis bundle."""

from __future__ import annotations

import argparse
from typing import Any

from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    require_v2_artifact,
    validate_note_plan_artifact,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True, help="Raw note-plan JSON object or file.")
    command.add_argument("--context", required=True, help="Schema-v2 synthesis bundle.")
    command.add_argument("--output", default="")
    return command


def build_note_plan_artifact(
    plan_source: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    require_v2_artifact(context, artifact_type="synthesis_bundle")
    plan = plan_source.get("note_plan", plan_source)
    if not isinstance(plan, dict):
        raise ContractError("note plan input must be an object")
    normalized = dict(plan)
    normalized.setdefault("paper_type", context.get("paper_type", "generic"))
    evidence_ids = {
        str(item.get("evidence_id", ""))
        for item in context.get("evidence_units", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    cited_ids = normalized.get("evidence_ids", []) or []
    if not isinstance(cited_ids, list):
        raise ContractError("note_plan.evidence_ids must be a list when present")
    unknown = sorted({str(item) for item in cited_ids if str(item) not in evidence_ids})
    if unknown:
        raise ContractError(f"note_plan references unknown evidence ids: {', '.join(unknown)}")

    artifact = artifact_header(
        "note_plan",
        paper_id=str(context["paper_id"]),
        run_id=str(context["run_id"]),
        status="pass",
    )
    artifact["note_plan"] = normalized
    artifact["evidence_reference_count"] = len(cited_ids)
    validate_note_plan_artifact(artifact)
    return artifact


def main() -> None:
    args = parser().parse_args()
    artifact = build_note_plan_artifact(
        load_json_object(args.input),
        load_json_object(args.context),
    )
    emit_json(artifact, args.output or None)


if __name__ == "__main__":
    main()

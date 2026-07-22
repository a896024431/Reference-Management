#!/usr/bin/env python3
"""Build a compact, single-copy evidence handoff bundle from v2 artifacts."""

from __future__ import annotations

import argparse
from typing import Any

from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    validate_evidence_pack_artifact,
    validate_paper_record_artifact,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--paper-record", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--visual-pages", default="")
    command.add_argument("--output", default="")
    return command


def _optional_artifact(value: str) -> dict[str, Any]:
    return load_json_object(value) if value else {}


def _check_optional_identity(
    paper_record: dict[str, Any],
    optional: dict[str, Any],
) -> None:
    if optional.get("schema_version") == "2.0":
        require_same_identity(paper_record, optional)


def build_bundle(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    visual_pages: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_paper_record_artifact(paper_record)
    validate_evidence_pack_artifact(
        evidence,
        paper_record_artifact=paper_record,
    )
    paper_id, run_id = require_same_identity(paper_record, evidence)
    visual_pages = visual_pages or {}
    _check_optional_identity(paper_record, visual_pages)

    record = paper_record["paper_record"]
    metadata = record["metadata"]
    pack = evidence.get("evidence_pack")
    if not isinstance(pack, dict):
        raise ContractError("evidence artifact is missing evidence_pack")
    units = [item for item in pack.get("evidence_units", []) if isinstance(item, dict)]
    paper_type = str(pack.get("paper_type", "generic"))
    status = str(evidence["status"])
    failures = list(evidence.get("failures", []))

    artifact = artifact_header(
        "synthesis_bundle",
        paper_id=paper_id,
        run_id=run_id,
        status=status,
        failures=failures,
    )
    artifact.update(
        {
            "title": metadata.get("title", ""),
            "metadata": metadata,
            "document_index": record.get("documents", []),
            "paper_type": paper_type,
            "paper_type_rationale": pack.get("paper_type_rationale", ""),
            "evidence_quality": pack.get("evidence_quality", "unknown"),
            "coverage": pack.get("coverage", {}),
            "evidence_units": units,
            "figure_captions": pack.get("figure_captions", []),
            "table_captions": pack.get("table_captions", []),
            "visual_pages": visual_pages,
            "summary": evidence.get("summary", {}),
        }
    )
    return artifact


def main() -> None:
    args = parser().parse_args()
    artifact = build_bundle(
        load_json_object(args.paper_record),
        load_json_object(args.evidence),
        _optional_artifact(args.visual_pages),
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

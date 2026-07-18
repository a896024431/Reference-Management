#!/usr/bin/env python3
"""Canonical figure contracts aligned with the repository-wide v2 schema.

The earlier figure helper remains an implementation layer.  This module is the
only public v2 boundary: artifacts always use schema ``2.0`` and statuses
``pass | degraded | fail`` from :mod:`contracts_v2`.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import figure_contracts as _legacy
from contracts_v2 import SCHEMA_VERSION, artifact_header, require_same_identity

FigureContractError = _legacy.FigureContractError
build_figure_asset_identity = _legacy.build_figure_asset_identity
bbox_sha256 = _legacy.bbox_sha256
ensure_asset_identity = _legacy.ensure_asset_identity
normalize_figure_label = _legacy.normalize_figure_label
sha256_bytes = _legacy.sha256_bytes
sha256_file = _legacy.sha256_file
render_figure_decision_block = _legacy.render_figure_decision_block
figure_note_alignment_issues = _legacy.figure_note_alignment_issues


_TO_LEGACY_STATUS = {"pass": "ok", "degraded": "degraded", "fail": "failed"}
_FROM_LEGACY_STATUS = {
    "ok": "pass",
    "pass": "pass",
    "degraded": "degraded",
    "failed": "fail",
    "fail": "fail",
}


def _nested(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return deepcopy(value if isinstance(value, dict) else record)


def _legacy_copy(artifact: dict[str, Any]) -> dict[str, Any]:
    copied = deepcopy(artifact)
    copied["status"] = _TO_LEGACY_STATUS.get(
        str(copied.get("status", "")), str(copied.get("status", ""))
    )
    return copied


def make_figure_manifest(
    *,
    paper_id: str,
    run_id: str,
    assets: Iterable[dict[str, Any]],
    failures: Iterable[str] = (),
    status: str = "pass",
) -> dict[str, Any]:
    payload = artifact_header(
        "figure_manifest", paper_id=paper_id, run_id=run_id, status=status, failures=failures
    )
    payload["assets"] = [ensure_asset_identity(asset) for asset in assets]
    return payload


def normalize_figure_manifest(
    record: dict[str, Any], *, verify_files: bool = False
) -> dict[str, Any]:
    raw = _nested(record, "figure_manifest")
    requested_status = _FROM_LEGACY_STATUS.get(str(raw.get("status", "")), "fail")
    existing_failures = list(raw.get("failures", []) or [])
    paper_id = str(raw.get("paper_id", ""))
    run_id = str(raw.get("run_id", ""))
    assets = raw.get("assets", []) if isinstance(raw.get("assets"), list) else []
    try:
        artifact = make_figure_manifest(
            paper_id=paper_id,
            run_id=run_id,
            assets=assets,
            failures=existing_failures,
            status=requested_status,
        )
    except Exception as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "figure_manifest",
            "paper_id": paper_id,
            "run_id": run_id,
            "status": "fail",
            "failures": sorted(set(existing_failures + [f"figure_manifest_header_invalid:{exc}"])),
            "assets": assets,
        }
    issues = _legacy.validate_figure_manifest(_legacy_copy(artifact), verify_files=verify_files)
    artifact["failures"] = sorted(set(existing_failures + issues))
    if artifact["failures"]:
        artifact["status"] = "fail"
    return artifact


def make_figure_decisions(
    *,
    paper_id: str,
    run_id: str,
    decisions: Iterable[dict[str, Any]],
    failures: Iterable[str] = (),
    status: str = "pass",
) -> dict[str, Any]:
    payload = artifact_header(
        "figure_decisions", paper_id=paper_id, run_id=run_id, status=status, failures=failures
    )
    payload["decisions"] = [dict(decision) for decision in decisions]
    return payload


def normalize_figure_decisions(
    record: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
    require_final: bool = False,
) -> dict[str, Any]:
    raw = _nested(record, "figure_decisions")
    paper_id = str(raw.get("paper_id", ""))
    run_id = str(raw.get("run_id", ""))
    existing_failures = list(raw.get("failures", []) or [])
    entries = raw.get("decisions", []) if isinstance(raw.get("decisions"), list) else []
    requested_status = _FROM_LEGACY_STATUS.get(str(raw.get("status", "")), "fail")
    try:
        artifact = make_figure_decisions(
            paper_id=paper_id,
            run_id=run_id,
            decisions=entries,
            failures=existing_failures,
            status=requested_status,
        )
    except Exception as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "figure_decisions",
            "paper_id": paper_id,
            "run_id": run_id,
            "status": "fail",
            "failures": sorted(set(existing_failures + [f"figure_decisions_header_invalid:{exc}"])),
            "decisions": entries,
        }
    canonical_manifest = normalize_figure_manifest(manifest) if manifest is not None else None
    legacy_manifest = _legacy_copy(canonical_manifest) if canonical_manifest is not None else None
    issues = _legacy.validate_figure_decisions(_legacy_copy(artifact), manifest=legacy_manifest)
    if canonical_manifest is not None:
        try:
            require_same_identity(artifact, canonical_manifest)
        except Exception as exc:
            issues.append(f"figure_contract_identity_invalid:{exc}")
    if require_final:
        for index, decision in enumerate(entries):
            if not isinstance(decision, dict):
                continue
            reason = str(decision.get("decision_reason", ""))
            outcome = str(decision.get("decision", ""))
            if reason == "awaiting_semantic_confirmation":
                issues.append(f"figure_decision_{index}_semantic_review_pending")
            if outcome in {"placeholder", "omitted"} and not reason:
                issues.append(f"figure_decision_{index}_final_reason_missing")
    artifact["failures"] = sorted(set(existing_failures + issues))
    if artifact["failures"]:
        artifact["status"] = "fail"
    return artifact


def materialize_decision(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    target_id: str,
    destination_dir: str | Path,
) -> dict[str, Any]:
    canonical_manifest = normalize_figure_manifest(manifest, verify_files=True)
    canonical_decisions = normalize_figure_decisions(
        decisions, manifest=canonical_manifest, require_final=True
    )
    if canonical_manifest["status"] != "pass" or canonical_decisions["status"] != "pass":
        failures = canonical_manifest["failures"] + canonical_decisions["failures"]
        raise FigureContractError("; ".join(sorted(set(failures))))
    result = _legacy.materialize_decision(
        manifest=_legacy_copy(canonical_manifest),
        decisions=_legacy_copy(canonical_decisions),
        target_id=target_id,
        destination_dir=destination_dir,
    )
    result.update(
        artifact_header(
            "materialized_figure",
            paper_id=canonical_manifest["paper_id"],
            run_id=canonical_manifest["run_id"],
            status="pass",
        )
    )
    return result


def materialize_inserted_assets(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    destination_dir: str | Path,
) -> list[dict[str, Any]]:
    normalized = normalize_figure_decisions(decisions, manifest=manifest, require_final=True)
    return [
        materialize_decision(
            manifest=manifest,
            decisions=normalized,
            target_id=str(decision["target_id"]),
            destination_dir=destination_dir,
        )
        for decision in normalized.get("decisions", [])
        if isinstance(decision, dict) and decision.get("decision") == "inserted"
    ]

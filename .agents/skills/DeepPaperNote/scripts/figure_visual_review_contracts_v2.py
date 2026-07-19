#!/usr/bin/env python3
"""Hash-bound visual-review contracts for DeepPaperNote figure publication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from contracts_v2 import (
    ContractError,
    artifact_header,
    canonical_json_sha256,
    require_same_identity,
    require_v2_artifact,
)
from figure_contracts_v2 import normalize_figure_decisions, normalize_figure_manifest

VISUAL_REVIEW_FIELDS = ("complete", "identity", "readable")
INSERT_OVERRIDE_KEYS = ("decision", "override_decision", "recommended_decision", "outcome")

def _quality_status(asset: dict[str, Any]) -> str:
    signals = asset.get("quality_signals")
    if not isinstance(signals, dict):
        return "unknown"
    return str(signals.get("visual_quality_status", "unknown")).strip().lower() or "unknown"


def _index_assets(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(asset.get("asset_id", "")): asset
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict) and str(asset.get("asset_id", "")).strip()
    }


def _index_reviews(
    reviews: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    indexed: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for index, raw in enumerate(reviews):
        if not isinstance(raw, dict):
            failures.append(f"figure_visual_review_{index}_invalid")
            continue
        review = dict(raw)
        asset_id = str(review.get("asset_id", "")).strip()
        if not asset_id:
            failures.append(f"figure_visual_review_{index}_asset_id_missing")
            continue
        if asset_id in indexed:
            failures.append(f"figure_visual_review_duplicate_asset:{asset_id}")
            continue
        indexed[asset_id] = review
    return indexed, failures


def _attempts_insert_override(review: dict[str, Any]) -> bool:
    return any(
        str(review.get(key, "")).strip().lower() == "inserted" for key in INSERT_OVERRIDE_KEYS
    )


def _review_failures(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    reviews: list[dict[str, Any]],
) -> list[str]:
    assets = _index_assets(manifest)
    indexed_reviews, failures = _index_reviews(reviews)

    for asset_id, review in indexed_reviews.items():
        asset = assets.get(asset_id)
        if asset is None:
            failures.append(f"figure_visual_review_unknown_asset:{asset_id}")
            continue
        if _quality_status(asset) == "reject" and _attempts_insert_override(review):
            failures.append(f"figure_visual_review_reject_override_forbidden:{asset_id}")

    for index, decision in enumerate(decisions.get("decisions", [])):
        if not isinstance(decision, dict) or decision.get("decision") != "inserted":
            continue
        asset_id = str(decision.get("selected_asset_id", "")).strip()
        prefix = f"figure_visual_review_inserted_{index}"
        if not asset_id:
            failures.append(f"{prefix}_asset_id_missing")
            continue
        asset = assets.get(asset_id)
        if asset is None:
            failures.append(f"{prefix}_asset_unknown:{asset_id}")
            continue
        rejected_ids = {
            str(value).strip()
            for value in decision.get("rejected_asset_ids", [])
            if str(value).strip()
        }
        if asset_id in rejected_ids:
            failures.append(f"figure_visual_review_selected_asset_rejected:{asset_id}")
        if _quality_status(asset) != "usable":
            failures.append(
                f"figure_visual_review_selected_asset_not_usable:{asset_id}:"
                f"{_quality_status(asset)}"
            )
        review = indexed_reviews.get(asset_id)
        if review is None:
            failures.append(f"figure_visual_review_inserted_asset_unreviewed:{asset_id}")
            continue
        for field in VISUAL_REVIEW_FIELDS:
            value = review.get(field)
            if not isinstance(value, bool):
                failures.append(f"figure_visual_review_{asset_id}_{field}_not_explicit")
            elif not value:
                failures.append(f"figure_visual_review_{asset_id}_{field}_false")
    return sorted(set(failures))


def _normalize_inputs(
    manifest: dict[str, Any], decisions: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical_manifest = normalize_figure_manifest(manifest, verify_files=True)
    canonical_decisions = normalize_figure_decisions(
        decisions,
        manifest=canonical_manifest,
        require_final=True,
    )
    require_same_identity(canonical_manifest, canonical_decisions)
    return canonical_manifest, canonical_decisions


def build_figure_visual_review(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    review_source: dict[str, Any],
    contact_sheet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed review artifact for all inserted candidates."""
    canonical_manifest, canonical_decisions = _normalize_inputs(manifest, decisions)
    paper_id, run_id = require_same_identity(canonical_manifest, canonical_decisions)
    failures: list[str] = []
    reviewer = str(review_source.get("reviewer", "")).strip()
    if not reviewer:
        failures.append("figure_visual_review_reviewer_missing")
    raw_reviews = review_source.get("reviews", [])
    if not isinstance(raw_reviews, list):
        failures.append("figure_visual_review_reviews_invalid")
        reviews: list[dict[str, Any]] = []
    else:
        reviews = [dict(item) if isinstance(item, dict) else item for item in raw_reviews]
    failures.extend(
        _review_failures(
            manifest=canonical_manifest,
            decisions=canonical_decisions,
            reviews=reviews,
        )
    )

    inserted = [
        entry
        for entry in canonical_decisions.get("decisions", [])
        if isinstance(entry, dict) and entry.get("decision") == "inserted"
    ]
    contact_sheet_hash = ""
    if contact_sheet is None:
        if inserted:
            failures.append("figure_visual_review_contact_sheet_required")
    else:
        try:
            require_v2_artifact(
                contact_sheet,
                artifact_type="figure_contact_sheet",
                allow_statuses={"pass"},
            )
            require_same_identity(canonical_manifest, contact_sheet)
        except ContractError as exc:
            failures.append(f"figure_visual_review_contact_sheet_invalid:{exc}")
        expected_manifest_hash = canonical_json_sha256(canonical_manifest)
        if contact_sheet.get("manifest_sha256") != expected_manifest_hash:
            failures.append("figure_visual_review_contact_sheet_manifest_hash_mismatch")
        expected_decisions_hash = canonical_json_sha256(canonical_decisions)
        if contact_sheet.get("decisions_sha256") != expected_decisions_hash:
            failures.append("figure_visual_review_contact_sheet_decisions_hash_mismatch")
        contact_sheet_hash = canonical_json_sha256(contact_sheet)

    artifact = artifact_header(
        "figure_visual_review",
        paper_id=paper_id,
        run_id=run_id,
        status="pass" if not failures else "fail",
        failures=sorted(set(failures)),
    )
    artifact.update(
        {
            "hash_method": "canonical-json-v1",
            "manifest_sha256": canonical_json_sha256(canonical_manifest),
            "decisions_sha256": canonical_json_sha256(canonical_decisions),
            "contact_sheet_sha256": contact_sheet_hash,
            "reviewer": reviewer,
            "reviewed_at": str(review_source.get("reviewed_at", "")).strip()
            or datetime.now(timezone.utc).isoformat(),
            "reviews": reviews,
        }
    )
    return artifact


def validate_figure_visual_review(
    artifact: dict[str, Any],
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    contact_sheet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a stored visual review against the exact current inputs."""
    require_v2_artifact(
        artifact,
        artifact_type="figure_visual_review",
        allow_statuses={"pass"},
    )
    if artifact.get("failures"):
        raise ContractError("Passing figure_visual_review must not contain failures")
    canonical_manifest, canonical_decisions = _normalize_inputs(manifest, decisions)
    require_same_identity(artifact, canonical_manifest, canonical_decisions)
    if artifact.get("hash_method") != "canonical-json-v1":
        raise ContractError("Unsupported figure visual-review hash method")
    expected_manifest_hash = canonical_json_sha256(canonical_manifest)
    if artifact.get("manifest_sha256") != expected_manifest_hash:
        raise ContractError("Figure visual review manifest hash mismatch")
    expected_decisions_hash = canonical_json_sha256(canonical_decisions)
    if artifact.get("decisions_sha256") != expected_decisions_hash:
        raise ContractError("Figure visual review decisions hash mismatch")

    reviews = artifact.get("reviews")
    if not isinstance(reviews, list):
        raise ContractError("figure_visual_review.reviews must be a list")
    failures = _review_failures(
        manifest=canonical_manifest,
        decisions=canonical_decisions,
        reviews=reviews,
    )
    if failures:
        raise ContractError("Figure visual review failed: " + "; ".join(failures))

    inserted = any(
        isinstance(entry, dict) and entry.get("decision") == "inserted"
        for entry in canonical_decisions.get("decisions", [])
    )
    if contact_sheet is None:
        if inserted:
            raise ContractError("Inserted assets require the bound contact-sheet artifact")
        if artifact.get("contact_sheet_sha256"):
            raise ContractError("Stored contact-sheet hash cannot be verified without its artifact")
    else:
        require_v2_artifact(
            contact_sheet,
            artifact_type="figure_contact_sheet",
            allow_statuses={"pass"},
        )
        require_same_identity(artifact, contact_sheet)
        if contact_sheet.get("manifest_sha256") != expected_manifest_hash:
            raise ContractError("Contact-sheet manifest hash mismatch")
        if contact_sheet.get("decisions_sha256") != expected_decisions_hash:
            raise ContractError("Contact-sheet decisions hash mismatch")
        if artifact.get("contact_sheet_sha256") != canonical_json_sha256(contact_sheet):
            raise ContractError("Figure visual review contact-sheet hash mismatch")
    return artifact

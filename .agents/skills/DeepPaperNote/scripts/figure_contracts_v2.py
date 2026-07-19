#!/usr/bin/env python3
"""Canonical schema-v2 contracts and deterministic helpers for figures.

Extraction, planning, materialization, and publishing share this module so a
visual cannot silently change identity between stages. Figure artifacts use
only the repository-wide ``pass | degraded | fail`` status enum.
"""

from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from contracts_v2 import (
    ARTIFACT_STATUSES,
    SCHEMA_VERSION,
    artifact_header,
    require_same_identity,
    sha256_bytes,
    sha256_file,
)

FIGURE_SCHEMA_VERSION = SCHEMA_VERSION
FINAL_DECISIONS = {"inserted", "placeholder", "omitted"}
INSERTABLE_QUALITY = {"usable"}
SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"})
_SAFE_FILENAME_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpe?g|webp|gif|svg)", re.IGNORECASE
)


class FigureContractError(ValueError):
    """Raised when a figure artifact violates the v2 contract."""


def normalize_figure_label(label: str) -> str:
    """Normalize common main/supplement/extended-data figure spellings."""
    text = re.sub(r"\s+", " ", str(label or "").strip().lower())
    text = re.sub(r"^extended\s+data\s+figure\.?\s*", "extended data fig ", text)
    text = re.sub(r"^extended\s+data\s+fig\.?\s*", "extended data fig ", text)
    text = re.sub(r"^supplementary\s+figure\.?\s*", "fig s", text)
    text = re.sub(r"^supplementary\s+fig\.?\s*", "fig s", text)
    text = re.sub(r"^figure\.?\s*", "fig ", text)
    text = re.sub(r"^fig\.?\s*", "fig ", text)
    text = re.sub(r"^table\.?\s*", "table ", text)
    text = re.sub(r"\bs\s+(\d)", r"s\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .:|\t")


def _slug(value: str, *, fallback: str) -> str:
    normalized = normalize_figure_label(value)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return (slug or fallback)[:72]


def bbox_sha256(bbox: Iterable[float] | None) -> str:
    rounded = [round(float(value), 3) for value in (bbox or [])]
    encoded = json.dumps(rounded, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return sha256_bytes(encoded)


def _normalize_image_extension(extension: str) -> str:
    normalized = str(extension or "png").strip().lower().removeprefix(".")
    if f".{normalized}" not in SUPPORTED_IMAGE_EXTENSIONS:
        raise FigureContractError(f"Unsupported figure image extension: {extension!r}")
    return normalized


def _filename_issue(filename: str) -> str:
    if not filename:
        return "missing"
    if (
        filename != filename.strip()
        or Path(filename).is_absolute()
        or "/" in filename
        or "\\" in filename
        or ".." in filename
    ):
        return "unsafe"
    if Path(filename).suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        return "extension_unsupported"
    if _SAFE_FILENAME_RE.fullmatch(filename) is None:
        return "unsafe"
    return ""


def build_figure_asset_identity(
    *,
    document_id: str,
    page_number: int,
    label: str,
    bbox: Iterable[float] | None,
    extraction_level: str = "figure",
    content_sha256: str = "",
    extension: str = "png",
) -> tuple[str, str, str]:
    """Return collision-proof ``(asset_id, filename, bbox_hash)``."""
    bbox_hash = bbox_sha256(bbox)
    asset_id, filename = _asset_identity_from_hash(
        document_id=document_id,
        page_number=page_number,
        label=label,
        bbox_hash=bbox_hash,
        extraction_level=extraction_level,
        content_sha256=content_sha256,
        extension=extension,
    )
    return asset_id, filename, bbox_hash


def _asset_identity_from_hash(
    *,
    document_id: str,
    page_number: int,
    label: str,
    bbox_hash: str,
    extraction_level: str,
    content_sha256: str,
    extension: str,
) -> tuple[str, str]:
    """Rebuild deterministic identity from the fields persisted in a manifest."""
    normalized_label = normalize_figure_label(label)
    identity = {
        "document_id": str(document_id or "main"),
        "page_number": int(page_number),
        "label": normalized_label,
        "bbox_sha256": bbox_hash,
        "extraction_level": str(extraction_level or "figure"),
        "content_sha256": str(content_sha256 or ""),
    }
    digest = sha256_bytes(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    )[:16]
    doc_slug = _slug(str(document_id or "main"), fallback="main")[:32]
    label_slug = _slug(normalized_label, fallback="visual")[:40]
    asset_id = f"fig-{doc_slug}-p{int(page_number):04d}-{label_slug}-{digest}"
    safe_ext = _normalize_image_extension(extension)
    return asset_id, f"{asset_id}.{safe_ext}"


def ensure_asset_identity(asset: dict[str, Any], *, document_id: str = "main") -> dict[str, Any]:
    """Return a copy of an asset with deterministic identity fields filled."""
    item = dict(asset)
    source_path = Path(str(item.get("path", ""))).expanduser()
    file_hash = str(item.get("file_sha256", ""))
    if not file_hash and source_path.is_file():
        file_hash = sha256_file(source_path)
    label = str(item.get("label", ""))
    page_number = int(item.get("page_number", 0) or 0)
    resolved_document = str(item.get("document_id", "") or document_id or "main")
    extension = str(
        item.get("ext", "") or Path(str(item.get("filename", ""))).suffix or "png"
    )
    asset_id, filename, bbox_hash = build_figure_asset_identity(
        document_id=resolved_document,
        page_number=page_number,
        label=label,
        bbox=item.get("bbox_pt", []),
        extraction_level=str(item.get("extraction_level", "figure")),
        content_sha256=file_hash,
        extension=extension,
    )
    item.setdefault("asset_id", asset_id)
    item.setdefault("filename", filename)
    item.setdefault("document_id", resolved_document)
    item.setdefault("bbox_sha256", bbox_hash)
    if file_hash:
        item["file_sha256"] = file_hash
    return item


def index_manifest_assets(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(asset.get("asset_id")): asset
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }


def validate_figure_manifest(
    manifest: dict[str, Any],
    *,
    verify_files: bool = False,
) -> list[str]:
    issues: list[str] = []
    if manifest.get("schema_version") != FIGURE_SCHEMA_VERSION:
        issues.append("figure_manifest_schema_version_invalid")
    if manifest.get("artifact_type") != "figure_manifest":
        issues.append("figure_manifest_artifact_type_invalid")
    if not str(manifest.get("paper_id", "")).strip():
        issues.append("figure_manifest_paper_id_missing")
    if not str(manifest.get("run_id", "")).strip():
        issues.append("figure_manifest_run_id_missing")
    if manifest.get("status") not in ARTIFACT_STATUSES:
        issues.append("figure_manifest_status_invalid")
    if not isinstance(manifest.get("failures"), list):
        issues.append("figure_manifest_failures_invalid")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        return sorted(set(issues + ["figure_manifest_assets_invalid"]))

    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    for index, asset in enumerate(assets):
        prefix = f"figure_manifest_asset_{index}"
        if not isinstance(asset, dict):
            issues.append(f"{prefix}_invalid")
            continue
        asset_id = str(asset.get("asset_id", ""))
        filename = str(asset.get("filename", ""))
        if not asset_id:
            issues.append(f"{prefix}_asset_id_missing")
        elif _SAFE_FILENAME_RE.fullmatch(f"{asset_id}.png") is None:
            issues.append(f"{prefix}_asset_id_unsafe")
        elif asset_id in seen_ids:
            issues.append("figure_manifest_duplicate_asset_id")
        seen_ids.add(asset_id)

        filename_problem = _filename_issue(filename)
        if filename_problem:
            issues.append(f"{prefix}_filename_{filename_problem}")
        elif Path(filename).stem != asset_id:
            issues.append(f"{prefix}_filename_identity_mismatch")
        elif filename in seen_filenames:
            issues.append("figure_manifest_duplicate_filename")
        seen_filenames.add(filename)

        if not str(asset.get("document_id", "")):
            issues.append(f"{prefix}_document_id_missing")
        try:
            page_number = int(asset.get("page_number", 0) or 0)
        except (TypeError, ValueError):
            page_number = 0
        if page_number <= 0:
            issues.append(f"{prefix}_page_number_invalid")
        if not normalize_figure_label(str(asset.get("label", ""))):
            issues.append(f"{prefix}_label_missing")

        file_hash = str(asset.get("file_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", file_hash):
            issues.append(f"{prefix}_file_sha256_invalid")
        bbox_hash = str(asset.get("bbox_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", bbox_hash):
            issues.append(f"{prefix}_bbox_sha256_invalid")
        if "bbox_pt" in asset and bbox_hash and bbox_sha256(asset.get("bbox_pt", [])) != bbox_hash:
            issues.append(f"{prefix}_bbox_sha256_mismatch")

        if (
            page_number > 0
            and asset_id
            and not filename_problem
            and re.fullmatch(r"[0-9a-f]{64}", file_hash)
            and re.fullmatch(r"[0-9a-f]{64}", bbox_hash)
        ):
            try:
                expected_id, expected_filename = _asset_identity_from_hash(
                    document_id=str(asset.get("document_id", "")),
                    page_number=page_number,
                    label=str(asset.get("label", "")),
                    bbox_hash=bbox_hash,
                    extraction_level=str(asset.get("extraction_level", "figure")),
                    content_sha256=file_hash,
                    extension=Path(filename).suffix,
                )
            except (FigureContractError, TypeError, ValueError):
                issues.append(f"{prefix}_identity_fields_invalid")
            else:
                if asset_id != expected_id:
                    issues.append(f"{prefix}_asset_id_identity_mismatch")
                if filename != expected_filename:
                    issues.append(f"{prefix}_filename_identity_mismatch")

        if verify_files:
            source = Path(str(asset.get("path", ""))).expanduser()
            if not source.is_file():
                issues.append(f"{prefix}_source_missing")
            elif file_hash and sha256_file(source) != file_hash:
                issues.append(f"{prefix}_source_hash_mismatch")
    return sorted(set(issues))


def validate_figure_decisions(
    decisions: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    if decisions.get("schema_version") != FIGURE_SCHEMA_VERSION:
        issues.append("figure_decisions_schema_version_invalid")
    if decisions.get("artifact_type") != "figure_decisions":
        issues.append("figure_decisions_artifact_type_invalid")
    if not str(decisions.get("paper_id", "")).strip():
        issues.append("figure_decisions_paper_id_missing")
    if not str(decisions.get("run_id", "")).strip():
        issues.append("figure_decisions_run_id_missing")
    if decisions.get("status") not in ARTIFACT_STATUSES:
        issues.append("figure_decisions_status_invalid")
    if not isinstance(decisions.get("failures"), list):
        issues.append("figure_decisions_failures_invalid")

    manifest_assets = index_manifest_assets(manifest or {})
    if manifest is not None:
        if decisions.get("paper_id") != manifest.get("paper_id"):
            issues.append("figure_contract_paper_id_mismatch")
        if decisions.get("run_id") != manifest.get("run_id"):
            issues.append("figure_contract_run_id_mismatch")

    entries = decisions.get("decisions")
    if not isinstance(entries, list):
        return sorted(set(issues + ["figure_decisions_entries_invalid"]))
    seen_targets: set[str] = set()
    for index, decision in enumerate(entries):
        prefix = f"figure_decision_{index}"
        if not isinstance(decision, dict):
            issues.append(f"{prefix}_invalid")
            continue
        target_id = str(decision.get("target_id", "")).strip()
        outcome = str(decision.get("decision", ""))
        selected_id = str(decision.get("selected_asset_id", ""))
        if not target_id:
            issues.append(f"{prefix}_target_id_missing")
        elif target_id in seen_targets:
            issues.append("figure_decisions_duplicate_target_id")
        seen_targets.add(target_id)
        if outcome not in FINAL_DECISIONS:
            issues.append(f"{prefix}_outcome_invalid")
        if outcome == "inserted" and not selected_id:
            issues.append(f"{prefix}_selected_asset_missing")
        if outcome != "inserted" and selected_id:
            issues.append(f"{prefix}_noninserted_has_selected_asset")

        candidate_ids = decision.get("candidate_asset_ids", [])
        rejected_values = decision.get("rejected_asset_ids", [])
        if not isinstance(candidate_ids, list):
            issues.append(f"{prefix}_candidate_asset_ids_invalid")
            candidate_ids = []
        if not isinstance(rejected_values, list):
            issues.append(f"{prefix}_rejected_asset_ids_invalid")
            rejected_values = []
        rejected_ids = set(rejected_values)
        if selected_id and selected_id not in candidate_ids:
            issues.append(f"{prefix}_selected_asset_not_candidate")
        if selected_id in rejected_ids:
            issues.append(f"{prefix}_selected_asset_rejected")
        if manifest is not None:
            for asset_id in list(candidate_ids) + list(rejected_ids):
                if asset_id and asset_id not in manifest_assets:
                    issues.append(f"{prefix}_unknown_asset_id")
            selected = manifest_assets.get(selected_id)
            if selected is not None:
                quality = selected.get("quality_signals", {})
                visual_status = (
                    quality.get("visual_quality_status", "") if isinstance(quality, dict) else ""
                )
                if visual_status not in INSERTABLE_QUALITY:
                    issues.append(f"{prefix}_selected_asset_not_usable")
    return sorted(set(issues))


def _nested(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return deepcopy(value if isinstance(value, dict) else record)


def _raw_failures(raw: dict[str, Any], *, prefix: str) -> tuple[list[str], list[str]]:
    value = raw.get("failures", [])
    if not isinstance(value, list):
        return [], [f"{prefix}_failures_invalid"]
    return [str(item) for item in value if str(item).strip()], []


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
    paper_id = str(raw.get("paper_id", ""))
    run_id = str(raw.get("run_id", ""))
    existing_failures, seed_issues = _raw_failures(raw, prefix="figure_manifest")
    raw_assets = raw.get("assets")
    if not isinstance(raw_assets, list):
        seed_issues.append("figure_manifest_assets_invalid")
        assets: list[dict[str, Any]] = []
    else:
        assets = raw_assets
    requested_status = str(raw.get("status", ""))
    if requested_status not in ARTIFACT_STATUSES:
        seed_issues.append("figure_manifest_status_invalid")
        requested_status = "fail"
    if raw.get("schema_version") != SCHEMA_VERSION:
        seed_issues.append("figure_manifest_schema_version_invalid")
    if raw.get("artifact_type") != "figure_manifest":
        seed_issues.append("figure_manifest_artifact_type_invalid")
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
            "failures": sorted(
                set(existing_failures + seed_issues + [f"figure_manifest_invalid:{exc}"])
            ),
            "assets": assets,
        }
    issues = seed_issues + validate_figure_manifest(artifact, verify_files=verify_files)
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
    existing_failures, seed_issues = _raw_failures(raw, prefix="figure_decisions")
    raw_entries = raw.get("decisions")
    if not isinstance(raw_entries, list):
        seed_issues.append("figure_decisions_entries_invalid")
        entries: list[dict[str, Any]] = []
    else:
        entries = raw_entries
    requested_status = str(raw.get("status", ""))
    if requested_status not in ARTIFACT_STATUSES:
        seed_issues.append("figure_decisions_status_invalid")
        requested_status = "fail"
    if raw.get("schema_version") != SCHEMA_VERSION:
        seed_issues.append("figure_decisions_schema_version_invalid")
    if raw.get("artifact_type") != "figure_decisions":
        seed_issues.append("figure_decisions_artifact_type_invalid")
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
            "failures": sorted(
                set(existing_failures + seed_issues + [f"figure_decisions_invalid:{exc}"])
            ),
            "decisions": entries,
        }
    canonical_manifest = normalize_figure_manifest(manifest) if manifest is not None else None
    issues = seed_issues + validate_figure_decisions(artifact, manifest=canonical_manifest)
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


def _decision_for_target(decisions: dict[str, Any], target_id: str) -> dict[str, Any]:
    for decision in decisions.get("decisions", []):
        if isinstance(decision, dict) and str(decision.get("target_id", "")) == target_id:
            return decision
    raise FigureContractError(f"Unknown figure target: {target_id}")


def _resolved_image_destination(destination_root: Path, filename: str) -> Path:
    problem = _filename_issue(filename)
    if problem:
        raise FigureContractError(f"Unsafe figure filename ({problem}): {filename!r}")
    destination = (destination_root / filename).resolve()
    try:
        relative = destination.relative_to(destination_root)
    except ValueError as exc:
        raise FigureContractError(
            f"Figure destination escapes images directory: {destination}"
        ) from exc
    if len(relative.parts) != 1 or destination.parent != destination_root:
        raise FigureContractError(f"Figure destination is not a direct image child: {destination}")
    return destination


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

    decision = _decision_for_target(canonical_decisions, target_id)
    if decision.get("decision") != "inserted":
        raise FigureContractError(f"Figure target {target_id!r} is not marked inserted")
    asset_id = str(decision.get("selected_asset_id", ""))
    asset = index_manifest_assets(canonical_manifest)[asset_id]
    source = Path(str(asset["path"])).expanduser().resolve()
    source_hash = str(asset["file_sha256"])

    destination_root = Path(destination_dir).expanduser().resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = _resolved_image_destination(destination_root, str(asset["filename"]))
    if destination.exists() and sha256_file(destination) != source_hash:
        raise FigureContractError(f"Refusing to overwrite non-matching figure asset: {destination}")
    if not destination.exists():
        shutil.copy2(source, destination)
    destination = _resolved_image_destination(destination_root, str(asset["filename"]))
    if sha256_file(destination) != source_hash:
        raise FigureContractError(f"Materialized figure hash mismatch: {destination}")

    result = artifact_header(
        "materialized_figure",
        paper_id=canonical_manifest["paper_id"],
        run_id=canonical_manifest["run_id"],
        status="pass",
    )
    result.update(
        {
            "target_id": target_id,
            "asset_id": asset_id,
            "label": asset.get("label", target_id),
            "source_path": str(source),
            "dest_image_path": str(destination),
            "filename": destination.name,
            "file_sha256": source_hash,
        }
    )
    return result


def materialize_inserted_assets(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    destination_dir: str | Path,
) -> list[dict[str, Any]]:
    canonical_manifest = normalize_figure_manifest(manifest, verify_files=True)
    canonical_decisions = normalize_figure_decisions(
        decisions, manifest=canonical_manifest, require_final=True
    )
    if canonical_manifest["status"] != "pass" or canonical_decisions["status"] != "pass":
        failures = canonical_manifest["failures"] + canonical_decisions["failures"]
        raise FigureContractError("; ".join(sorted(set(failures))))
    return [
        materialize_decision(
            manifest=canonical_manifest,
            decisions=canonical_decisions,
            target_id=str(decision["target_id"]),
            destination_dir=destination_dir,
        )
        for decision in canonical_decisions.get("decisions", [])
        if isinstance(decision, dict) and decision.get("decision") == "inserted"
    ]


def figure_note_alignment_issues(
    note_text: str,
    decisions: dict[str, Any],
    *,
    materialized: Iterable[dict[str, Any]] | None = None,
) -> list[str]:
    """Check that inserted decisions are represented truthfully in note text."""
    materialized_by_target = {
        str(item.get("target_id", "")): item
        for item in (materialized or [])
        if isinstance(item, dict)
    }
    issues: list[str] = []
    for decision in decisions.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        target = str(decision.get("target_id", ""))
        if decision.get("decision") == "inserted":
            item = materialized_by_target.get(target)
            if item is None:
                issues.append(f"figure_inserted_not_materialized:{target}")
                continue
            if str(item.get("filename", "")) not in note_text:
                issues.append(f"figure_inserted_embed_missing:{target}")
    return issues

#!/usr/bin/env python3
"""Versioned contracts and deterministic helpers for DeepPaperNote figures.

The extraction, planning, materialization, and publish stages all use this
module so that a visual cannot silently change identity between stages.  The
helpers deliberately contain no paper-understanding logic: semantic importance
and the final insert/placeholder/omit choice still belong to the model.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

FIGURE_SCHEMA_VERSION = "2.0"
FINAL_DECISIONS = {"inserted", "placeholder", "omitted"}
INSERTABLE_QUALITY = {"usable"}


class FigureContractError(ValueError):
    """Raised when a figure artifact violates the v2 contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    """Return collision-proof ``(asset_id, filename, bbox_hash)``.

    Identity includes the document, page, normalized original label, extraction
    level, and crop coordinates.  A short content digest is included when
    available, preventing a silently changed render from reusing an old name.
    """
    normalized_label = normalize_figure_label(label)
    bbox_hash = bbox_sha256(bbox)
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
    safe_ext = re.sub(r"[^a-z0-9]", "", str(extension or "png").lower()) or "png"
    return asset_id, f"{asset_id}.{safe_ext}", bbox_hash


def ensure_asset_identity(asset: dict[str, Any], *, document_id: str = "main") -> dict[str, Any]:
    """Return a copy of an asset with v2 identity fields filled when absent."""
    item = dict(asset)
    source_path = Path(str(item.get("path", ""))).expanduser()
    file_hash = str(item.get("file_sha256", ""))
    if not file_hash and source_path.is_file():
        file_hash = sha256_file(source_path)
    label = str(item.get("label", ""))
    page_number = int(item.get("page_number", 0) or 0)
    resolved_document = str(item.get("document_id", "") or document_id or "main")
    ext = str(
        item.get("ext", "") or Path(str(item.get("filename", ""))).suffix.lstrip(".") or "png"
    )
    asset_id, filename, bbox_hash = build_figure_asset_identity(
        document_id=resolved_document,
        page_number=page_number,
        label=label,
        bbox=item.get("bbox_pt", []),
        extraction_level=str(item.get("extraction_level", "figure")),
        content_sha256=file_hash,
        extension=ext,
    )
    item.setdefault("asset_id", asset_id)
    item.setdefault("filename", filename)
    item.setdefault("document_id", resolved_document)
    item.setdefault("bbox_sha256", bbox_hash)
    if file_hash:
        item["file_sha256"] = file_hash
    return item


def make_figure_manifest(
    *,
    paper_id: str,
    run_id: str,
    assets: Iterable[dict[str, Any]],
    failures: Iterable[str] | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    normalized = [ensure_asset_identity(asset) for asset in assets]
    return {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "paper_id": str(paper_id or ""),
        "run_id": str(run_id or ""),
        "status": status,
        "failures": list(failures or []),
        "assets": normalized,
    }


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
    if not str(manifest.get("paper_id", "")).strip():
        issues.append("figure_manifest_paper_id_missing")
    if not str(manifest.get("run_id", "")).strip():
        issues.append("figure_manifest_run_id_missing")
    if manifest.get("status") not in {"ok", "degraded", "failed"}:
        issues.append("figure_manifest_status_invalid")
    if not isinstance(manifest.get("failures"), list):
        issues.append("figure_manifest_failures_invalid")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        return issues + ["figure_manifest_assets_invalid"]

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
        elif asset_id in seen_ids:
            issues.append("figure_manifest_duplicate_asset_id")
        seen_ids.add(asset_id)
        if not filename:
            issues.append(f"{prefix}_filename_missing")
        elif filename in seen_filenames:
            issues.append("figure_manifest_duplicate_filename")
        seen_filenames.add(filename)
        if not str(asset.get("document_id", "")):
            issues.append(f"{prefix}_document_id_missing")
        if int(asset.get("page_number", 0) or 0) <= 0:
            issues.append(f"{prefix}_page_number_invalid")
        if not normalize_figure_label(str(asset.get("label", ""))):
            issues.append(f"{prefix}_label_missing")
        file_hash = str(asset.get("file_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", file_hash):
            issues.append(f"{prefix}_file_sha256_invalid")
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
    if not str(decisions.get("paper_id", "")).strip():
        issues.append("figure_decisions_paper_id_missing")
    if not str(decisions.get("run_id", "")).strip():
        issues.append("figure_decisions_run_id_missing")
    if decisions.get("status") not in {"ok", "degraded", "failed"}:
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
        return issues + ["figure_decisions_entries_invalid"]
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
        rejected_ids = set(decision.get("rejected_asset_ids", []) or [])
        if not isinstance(candidate_ids, list):
            issues.append(f"{prefix}_candidate_asset_ids_invalid")
            candidate_ids = []
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


def _decision_for_target(decisions: dict[str, Any], target_id: str) -> dict[str, Any]:
    for decision in decisions.get("decisions", []):
        if isinstance(decision, dict) and str(decision.get("target_id", "")) == target_id:
            return decision
    raise FigureContractError(f"Unknown figure target: {target_id}")


def materialize_decision(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    target_id: str,
    destination_dir: str | Path,
) -> dict[str, Any]:
    """Copy one explicitly inserted, verified asset to a note image folder."""
    issues = validate_figure_manifest(manifest, verify_files=True)
    issues.extend(validate_figure_decisions(decisions, manifest=manifest))
    if issues:
        raise FigureContractError("; ".join(sorted(set(issues))))
    decision = _decision_for_target(decisions, target_id)
    if decision.get("decision") != "inserted":
        raise FigureContractError(f"Figure target {target_id!r} is not marked inserted")
    asset_id = str(decision.get("selected_asset_id", ""))
    asset = index_manifest_assets(manifest)[asset_id]
    source = Path(str(asset["path"])).expanduser().resolve()
    destination_root = Path(destination_dir).expanduser().resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / str(asset["filename"])
    source_hash = str(asset["file_sha256"])
    if destination.exists() and sha256_file(destination) != source_hash:
        raise FigureContractError(f"Refusing to overwrite non-matching figure asset: {destination}")
    if not destination.exists():
        shutil.copy2(source, destination)
    if sha256_file(destination) != source_hash:
        raise FigureContractError(f"Materialized figure hash mismatch: {destination}")
    return {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "paper_id": manifest["paper_id"],
        "run_id": manifest["run_id"],
        "target_id": target_id,
        "asset_id": asset_id,
        "label": asset.get("label", target_id),
        "source_path": str(source),
        "dest_image_path": str(destination),
        "filename": destination.name,
        "file_sha256": source_hash,
    }


def materialize_inserted_assets(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    destination_dir: str | Path,
) -> list[dict[str, Any]]:
    return [
        materialize_decision(
            manifest=manifest,
            decisions=decisions,
            target_id=str(decision["target_id"]),
            destination_dir=destination_dir,
        )
        for decision in decisions.get("decisions", [])
        if isinstance(decision, dict) and decision.get("decision") == "inserted"
    ]


def render_figure_decision_block(
    decision: dict[str, Any],
    *,
    embed: str = "",
) -> str:
    """Render an inserted figure as an embed and natural caption only.

    Figure decisions, target sections, candidate rankings, and QA state belong in
    run artifacts. A placeholder or omitted decision has no reader-visible block.
    """
    if decision.get("decision") != "inserted":
        return ""
    if not embed:
        target_id = str(decision.get("target_id", "")).strip()
        raise FigureContractError(f"Inserted figure {target_id!r} requires embed markup")
    target_id = str(decision.get("display_label", "") or decision.get("target_id", "")).strip()
    label = str(decision.get("short_label", "") or decision.get("caption", "")).strip()
    caption = f"{target_id} {label}".strip()
    lines = [embed]
    if caption:
        lines.extend(["", f"*{caption}*"])
    return "\n".join(lines)


def figure_note_alignment_issues(
    note_text: str,
    decisions: dict[str, Any],
    *,
    materialized: Iterable[dict[str, Any]] | None = None,
) -> list[str]:
    """Check that final decisions are represented truthfully in note text."""
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
        outcome = decision.get("decision")
        if outcome == "inserted":
            item = materialized_by_target.get(target)
            if item is None:
                issues.append(f"figure_inserted_not_materialized:{target}")
                continue
            if str(item.get("filename", "")) not in note_text:
                issues.append(f"figure_inserted_embed_missing:{target}")
        # Placeholder decisions are recorded only in the run artifacts.
    return issues

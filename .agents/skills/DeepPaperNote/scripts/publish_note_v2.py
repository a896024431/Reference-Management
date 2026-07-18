#!/usr/bin/env python3
"""Validate, archive, and atomically publish one schema-v2 paper note."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    note_plan_bound_evidence_ids,
    require_note_hash,
    require_same_identity,
    require_v2_artifact,
    validate_note_plan_artifact,
    validate_paper_record_artifact,
    validate_review_artifact,
)
from figure_contracts_v2 import (
    figure_note_alignment_issues,
    materialize_inserted_assets,
    normalize_figure_decisions,
    normalize_figure_manifest,
)
from figure_visual_review_contracts_v2 import (
    canonical_json_sha256,
    validate_figure_visual_review,
)
from lint_note_v2 import reader_visible_figure_metadata_issues
from vault import parse_frontmatter, validate_frontmatter_properties, validate_image_file

NOTE_FILENAME = "笔记.md"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--staging-dir", required=True)
    command.add_argument("--vault", required=True)
    command.add_argument("--paper-record", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--note-plan", required=True)
    command.add_argument("--lint", required=True)
    command.add_argument("--quality", required=True)
    command.add_argument("--readability", required=True)
    command.add_argument("--figure-manifest", required=True)
    command.add_argument("--figure-decisions", required=True)
    command.add_argument("--figure-contact-sheet", required=True)
    command.add_argument("--figure-visual-review", required=True)
    command.add_argument("--backup-root", default="")
    command.add_argument("--output", default="")
    command.add_argument("--dry-run", action="store_true")
    return command

def _safe_folder_name(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip().rstrip(".")
    if not cleaned:
        raise ContractError("Canonical title becomes empty after removing invalid path characters")
    return cleaned


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_remove_tree(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    if not _inside(resolved, allowed_root) or resolved == allowed_root.resolve():
        raise ContractError(
            f"Refusing recursive cleanup outside temporary publish root: {resolved}"
        )
    if resolved.exists():
        shutil.rmtree(resolved)


def _load_artifacts(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return {
        "paper_record": load_json_object(args.paper_record),
        "evidence_pack": load_json_object(args.evidence),
        "note_plan": load_json_object(args.note_plan),
        "lint_report": load_json_object(args.lint),
        "quality_review": load_json_object(args.quality),
        "readability_review": load_json_object(args.readability),
        "figure_manifest": load_json_object(args.figure_manifest),
        "figure_decisions": load_json_object(args.figure_decisions),
    }


def validate_visual_review_for_publish(
    *,
    visual_review: dict[str, Any],
    contact_sheet: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    """Bind the visual review to the same manifest, decisions, and run identity."""
    manifest = artifacts["figure_manifest"]
    decisions = artifacts["figure_decisions"]
    validate_figure_visual_review(
        visual_review,
        manifest=manifest,
        decisions=decisions,
        contact_sheet=contact_sheet,
    )
    require_same_identity(visual_review, contact_sheet, *artifacts.values())

def _referenced_image_names(note_text: str) -> set[str]:
    names: set[str] = set()
    for target in re.findall(r"!\[\[([^\]]+)\]\]", note_text):
        path = target.split("|", 1)[0].strip()
        names.add(Path(path).name)
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", note_text):
        names.add(Path(target.strip().strip("<>")).name)
    return names


def expected_evidence_level(paper_record: dict[str, Any]) -> str:
    documents = paper_record["paper_record"].get("documents", [])
    if not any(document.get("role") == "main" for document in documents):
        raise ContractError("Formal publishing requires one parsed main document")
    return (
        "full_text_supplement"
        if any(document.get("role") == "supplement" for document in documents)
        else "full_text"
    )


def expected_figure_status(decisions: dict[str, Any]) -> str:
    entries = [
        item for item in decisions.get("decisions", []) if isinstance(item, dict)
    ]
    if not entries:
        return "none_needed"
    outcomes = {str(item.get("decision", "")) for item in entries}
    has_placeholder = "placeholder" in outcomes
    has_inserted = "inserted" in outcomes
    if has_placeholder and has_inserted:
        return "partial"
    if has_placeholder:
        return "placeholder_only"
    return "complete"


def validate_staging_contents(staging_dir: Path) -> None:
    root_entries = {item.name for item in staging_dir.iterdir()}
    expected = {NOTE_FILENAME, "images"}
    if root_entries != expected:
        extras = sorted(root_entries - expected)
        missing = sorted(expected - root_entries)
        details = []
        if extras:
            details.append("extra=" + ",".join(extras))
        if missing:
            details.append("missing=" + ",".join(missing))
        raise ContractError(
            "Staging contents do not match the release contract: " + "; ".join(details)
        )
    image_dir = staging_dir / "images"
    if not image_dir.is_dir():
        raise ContractError("Staging directory is missing images/")
    invalid = [
        item.name
        for item in image_dir.iterdir()
        if not item.is_file() or item.suffix.lower() not in IMAGE_EXTENSIONS
    ]
    if invalid:
        raise ContractError(
            "Staging images/ contains non-image assets: " + ", ".join(sorted(invalid))
        )


def validate_note_plan_evidence(
    note_plan: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    pack = evidence.get("evidence_pack")
    if not isinstance(pack, dict):
        raise ContractError("evidence_pack payload is missing")
    known = {
        str(item.get("evidence_id", ""))
        for item in pack.get("evidence_units", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    cited = note_plan_bound_evidence_ids(note_plan["note_plan"])
    unknown = sorted(cited - known)
    if unknown:
        raise ContractError(
            "note_plan references evidence absent from evidence_pack: " + ", ".join(unknown)
        )


def validate_release(
    *,
    staging_dir: Path,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    paper_record = artifacts["paper_record"]
    evidence = artifacts["evidence_pack"]
    note_plan = artifacts["note_plan"]
    lint = artifacts["lint_report"]
    quality = artifacts["quality_review"]
    readability = artifacts["readability_review"]
    validate_paper_record_artifact(paper_record)
    require_v2_artifact(
        paper_record,
        artifact_type="paper_record",
        allow_statuses={"pass"},
    )
    require_v2_artifact(
        evidence,
        artifact_type="evidence_pack",
        allow_statuses={"pass"},
    )
    validate_note_plan_artifact(note_plan)
    validate_note_plan_evidence(note_plan, evidence)
    require_v2_artifact(lint, artifact_type="lint_report", allow_statuses={"pass"})
    validate_review_artifact(quality, kind="quality")
    validate_review_artifact(readability, kind="readability")
    if str(quality["author"]).casefold() != str(readability["author"]).casefold():
        raise ContractError("Quality and readability reviews must name the same note author")

    manifest = normalize_figure_manifest(artifacts["figure_manifest"], verify_files=True)
    decisions = normalize_figure_decisions(
        artifacts["figure_decisions"],
        manifest=manifest,
        require_final=True,
    )
    require_v2_artifact(manifest, artifact_type="figure_manifest", allow_statuses={"pass"})
    require_v2_artifact(decisions, artifact_type="figure_decisions", allow_statuses={"pass"})
    paper_id, run_id = require_same_identity(
        paper_record,
        evidence,
        note_plan,
        lint,
        quality,
        readability,
        manifest,
        decisions,
    )

    validate_staging_contents(staging_dir)
    note_path = staging_dir / NOTE_FILENAME
    image_dir = staging_dir / "images"
    note_text = note_path.read_text(encoding="utf-8")
    figure_metadata_issues = reader_visible_figure_metadata_issues(note_text)
    if figure_metadata_issues:
        codes = sorted({str(item["code"]) for item in figure_metadata_issues})
        raise ContractError(
            "Reader-visible figure metadata release gate failed: " + ", ".join(codes)
        )
    note_sha = require_note_hash(note_text, lint, quality, readability)
    parsed = parse_frontmatter(note_text)
    frontmatter_issues = validate_frontmatter_properties(parsed.properties)
    if parsed.errors or frontmatter_issues:
        codes = [*parsed.errors, *(item["code"] for item in frontmatter_issues)]
        raise ContractError("Frontmatter release gate failed: " + ", ".join(codes))
    if parsed.properties.get("note_status") != "polished":
        raise ContractError("Formal publishing requires note_status: polished")
    evidence_level = expected_evidence_level(paper_record)
    if parsed.properties.get("evidence_level") != evidence_level:
        raise ContractError(
            f"Frontmatter evidence_level must be {evidence_level!r} for these documents"
        )
    figure_status = expected_figure_status(decisions)
    if parsed.properties.get("figure_status") != figure_status:
        raise ContractError(
            f"Frontmatter figure_status must be {figure_status!r} for these decisions"
        )

    materialized = materialize_inserted_assets(
        manifest=manifest,
        decisions=decisions,
        destination_dir=image_dir,
    )
    validate_staging_contents(staging_dir)
    alignment = figure_note_alignment_issues(note_text, decisions, materialized=materialized)
    if alignment:
        raise ContractError("Figure/note alignment failed: " + "; ".join(alignment))
    referenced = _referenced_image_names(note_text)
    image_failures: list[str] = []
    for image in sorted(image_dir.iterdir()):
        corruption = validate_image_file(image)
        if corruption:
            image_failures.append(f"image_corrupt:{image.name}:{corruption}")
        if image.name not in referenced:
            image_failures.append(f"image_orphan:{image.name}")
    if image_failures:
        raise ContractError("Image release gate failed: " + "; ".join(image_failures))

    metadata = paper_record["paper_record"]["metadata"]
    title = str(metadata.get("title", "")).strip()
    if parsed.properties.get("title") != title:
        raise ContractError("Frontmatter title must match paper_record metadata.title")
    return {
        "paper_id": paper_id,
        "run_id": run_id,
        "title": title,
        "folder_name": _safe_folder_name(title),
        "note_sha256": note_sha,
        "manifest": manifest,
        "decisions": decisions,
        "materialized": materialized,
        "evidence_level": evidence_level,
        "figure_status": figure_status,
    }


def _prepare_directory(*, staging_dir: Path, prepared: Path) -> None:
    """Prepare only reader-facing Vault content."""
    prepared.mkdir(parents=True, exist_ok=False)
    shutil.copy2(staging_dir / NOTE_FILENAME, prepared / NOTE_FILENAME)
    shutil.copytree(staging_dir / "images", prepared / "images")


def publish_transaction(
    *,
    staging_dir: Path,
    vault: Path,
    backup_root: Path,
    release: dict[str, Any],
) -> tuple[Path, Path | None]:
    research = vault / "Research"
    research.mkdir(parents=True, exist_ok=True)
    target = research / release["folder_name"]
    prepared = research / f".{release['folder_name']}.publish-{uuid.uuid4().hex}"
    if not _inside(prepared, research):
        raise ContractError("Prepared publish directory escaped Research")
    _prepare_directory(staging_dir=staging_dir, prepared=prepared)

    backup_target: Path | None = None
    try:
        if target.exists():
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_target = backup_root / release["folder_name"]
            if backup_target.exists():
                raise ContractError(f"Backup target already exists: {backup_target}")
            if not _inside(target, research) or not _inside(backup_target, backup_root):
                raise ContractError("Publish or backup path escaped its intended root")
            os.replace(target, backup_target)
        os.replace(prepared, target)
    except Exception:
        if target.exists() and backup_target and backup_target.exists():
            failed_new = backup_root / f"{release['folder_name']}.failed-{uuid.uuid4().hex}"
            os.replace(target, failed_new)
        if backup_target and backup_target.exists() and not target.exists():
            os.replace(backup_target, target)
        if prepared.exists():
            _safe_remove_tree(prepared, allowed_root=research)
        raise
    return target, backup_target


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_target(vault: Path, run_id: str) -> Path:
    safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip(".-")
    if not safe_run_id or safe_run_id != run_id:
        raise ContractError(f"Unsafe run_id for audit directory: {run_id}")
    return vault / ".local" / "deeppapernote" / "published" / safe_run_id


def archive_publish_audit(
    *,
    vault: Path,
    target: Path,
    artifacts: dict[str, dict[str, Any]],
    contact_sheet: dict[str, Any],
    visual_review: dict[str, Any],
    release: dict[str, Any],
    report: dict[str, Any],
) -> Path:
    """Write a compact JSON-only audit outside the reader-facing Research tree."""
    audit_target = _audit_target(vault, release["run_id"])
    audit_root = audit_target.parent
    audit_root.mkdir(parents=True, exist_ok=True)
    temporary = audit_root / f".{release['run_id']}.audit-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for name, artifact in artifacts.items():
            emit_json(artifact, temporary / f"{name}.json")
        emit_json(contact_sheet, temporary / "figure_contact_sheet.json")
        emit_json(visual_review, temporary / "figure_visual_review.json")
        emit_json(report, temporary / "publish_report.json")
        image_records = []
        for image in sorted((target / "images").iterdir(), key=lambda item: item.name.casefold()):
            if image.is_file() and image.suffix.lower() in IMAGE_EXTENSIONS:
                image_records.append(
                    {
                        "name": image.name,
                        "sha256": _sha256_file(image),
                        "size_bytes": image.stat().st_size,
                    }
                )
        snapshot = artifact_header(
            "published_audit",
            paper_id=release["paper_id"],
            run_id=release["run_id"],
            status="pass",
        )
        snapshot.update(
            {
                "note": (
                    Path("Research") / release["folder_name"] / NOTE_FILENAME
                ).as_posix(),
                "note_sha256": release["note_sha256"],
                "note_file_sha256": _sha256_file(target / NOTE_FILENAME),
                "images": image_records,
                "artifact_files": sorted(path.name for path in temporary.glob("*.json")),
                "contact_sheet_sha256": canonical_json_sha256(contact_sheet),
                "visual_review_sha256": canonical_json_sha256(visual_review),
            }
        )
        emit_json(snapshot, temporary / "snapshot.json")
        previous = audit_root / f".{release['run_id']}.audit-old-{uuid.uuid4().hex}"
        if audit_target.exists():
            os.replace(audit_target, previous)
        try:
            os.replace(temporary, audit_target)
        except Exception:
            if previous.exists() and not audit_target.exists():
                os.replace(previous, audit_target)
            raise
        if previous.exists():
            _safe_remove_tree(previous, allowed_root=audit_root)
    except Exception:
        if temporary.exists():
            _safe_remove_tree(temporary, allowed_root=audit_root)
        raise
    return audit_target


def _rollback_after_audit_failure(
    *, target: Path, backup: Path | None, vault: Path
) -> None:
    research = vault / "Research"
    if target.exists():
        _safe_remove_tree(target, allowed_root=research)
    if backup and backup.exists():
        os.replace(backup, target)

def main() -> None:
    args = parser().parse_args()
    staging_dir = Path(args.staging_dir).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve()
    if not staging_dir.is_dir():
        raise SystemExit(f"Staging directory does not exist: {staging_dir}")
    if not vault.is_dir():
        raise SystemExit(f"Vault does not exist: {vault}")

    artifacts = _load_artifacts(args)
    contact_sheet = load_json_object(args.figure_contact_sheet)
    visual_review = load_json_object(args.figure_visual_review)
    validate_visual_review_for_publish(
        visual_review=visual_review,
        contact_sheet=contact_sheet,
        artifacts=artifacts,
    )
    release = validate_release(
        staging_dir=staging_dir,
        artifacts=artifacts,
    )
    backup_root = (
        Path(args.backup_root).expanduser().resolve()
        if args.backup_root
        else vault / ".local" / "deeppapernote" / "rollback" / release["run_id"]
    )
    predicted_target = vault / "Research" / release["folder_name"]
    predicted_audit = _audit_target(vault, release["run_id"])
    target: Path | None = None
    backup: Path | None = None

    report = artifact_header(
        "publish_report",
        paper_id=release["paper_id"],
        run_id=release["run_id"],
        status="pass",
    )
    report.update(
        {
            "publisher": "publish_note_v2",
            "dry_run": args.dry_run,
            "note_sha256": release["note_sha256"],
            "figure_visual_review_sha256": canonical_json_sha256(visual_review),
            "figure_contact_sheet_sha256": canonical_json_sha256(contact_sheet),
            "target": str(predicted_target),
            "audit": str(predicted_audit),
            "backup": "",
            "materialized_figures": release["materialized"],
            "evidence_level": release["evidence_level"],
            "figure_status": release["figure_status"],
        }
    )

    if not args.dry_run:
        target, backup = publish_transaction(
            staging_dir=staging_dir,
            vault=vault,
            backup_root=backup_root,
            release=release,
        )
        try:
            audit = archive_publish_audit(
                vault=vault,
                target=target,
                artifacts=artifacts,
                contact_sheet=contact_sheet,
                visual_review=visual_review,
                release=release,
                report=report,
            )
            report["audit"] = str(audit)
        except Exception:
            _rollback_after_audit_failure(target=target, backup=backup, vault=vault)
            raise
        if backup and backup.exists():
            _safe_remove_tree(backup, allowed_root=backup_root)
        if backup_root.exists() and not any(backup_root.iterdir()):
            backup_root.rmdir()

    emit_json(report, args.output or None)


if __name__ == "__main__":
    main()

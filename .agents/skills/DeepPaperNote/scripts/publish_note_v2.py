#!/usr/bin/env python3
"""Strictly validate and transactionally publish a staged v2 paper note directory."""

from __future__ import annotations

import argparse
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
from lint_note_release_v2 import reader_visible_figure_metadata_issues
from vault import parse_frontmatter, validate_frontmatter_properties, validate_image_file

NOTE_FILENAME = "笔记.md"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--staging-dir", required=True, help="Directory containing 笔记.md and images/."
    )
    command.add_argument("--vault", required=True)
    command.add_argument("--paper-record", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--note-plan", required=True)
    command.add_argument("--lint", required=True)
    command.add_argument("--quality", required=True)
    command.add_argument("--readability", required=True)
    command.add_argument("--figure-manifest", required=True)
    command.add_argument("--figure-decisions", required=True)
    command.add_argument("--backup-root", default="")
    command.add_argument("--output", default="")
    command.add_argument("--allow-degraded", action="store_true")
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


def _referenced_image_names(note_text: str) -> set[str]:
    names: set[str] = set()
    for target in re.findall(r"!\[\[([^\]]+)\]\]", note_text):
        path = target.split("|", 1)[0].strip()
        names.add(Path(path).name)
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", note_text):
        names.add(Path(target.strip().strip("<>")).name)
    return names


def validate_release(
    *,
    staging_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    allow_degraded: bool,
) -> dict[str, Any]:
    paper_record = artifacts["paper_record"]
    evidence = artifacts["evidence_pack"]
    note_plan = artifacts["note_plan"]
    lint = artifacts["lint_report"]
    quality = artifacts["quality_review"]
    readability = artifacts["readability_review"]
    validate_paper_record_artifact(paper_record)
    require_v2_artifact(
        evidence,
        artifact_type="evidence_pack",
        allow_statuses={"pass", "degraded"} if allow_degraded else {"pass"},
    )
    validate_note_plan_artifact(note_plan)
    require_v2_artifact(lint, artifact_type="lint_report", allow_statuses={"pass"})
    validate_review_artifact(quality, kind="quality")
    validate_review_artifact(readability, kind="readability")

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

    note_path = staging_dir / NOTE_FILENAME
    image_dir = staging_dir / "images"
    if not note_path.is_file():
        raise ContractError(f"Staging directory is missing {NOTE_FILENAME}")
    if not image_dir.is_dir():
        raise ContractError("Staging directory is missing images/")
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
    if evidence["status"] == "degraded" and parsed.properties.get("note_status") != "degraded":
        raise ContractError("Degraded evidence may only publish a note_status: degraded note")

    materialized = materialize_inserted_assets(
        manifest=manifest,
        decisions=decisions,
        destination_dir=image_dir,
    )
    alignment = figure_note_alignment_issues(note_text, decisions, materialized=materialized)
    if alignment:
        raise ContractError("Figure/note alignment failed: " + "; ".join(alignment))
    referenced = _referenced_image_names(note_text)
    image_failures: list[str] = []
    for image in sorted(image_dir.iterdir()):
        if not image.is_file() or image.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
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
    }


def _prepare_directory(
    *,
    staging_dir: Path,
    prepared: Path,
    artifacts: dict[str, dict[str, Any]],
    canonical_manifest: dict[str, Any],
    canonical_decisions: dict[str, Any],
) -> None:
    prepared.mkdir(parents=True, exist_ok=False)
    shutil.copy2(staging_dir / NOTE_FILENAME, prepared / NOTE_FILENAME)
    shutil.copytree(staging_dir / "images", prepared / "images")
    manifests_dir = prepared / "manifests"
    manifests_dir.mkdir()
    for name, artifact in artifacts.items():
        payload = artifact
        if name == "figure_manifest":
            payload = canonical_manifest
        elif name == "figure_decisions":
            payload = canonical_decisions
        emit_json(payload, manifests_dir / f"{name}.json")


def publish_transaction(
    *,
    staging_dir: Path,
    vault: Path,
    backup_root: Path,
    artifacts: dict[str, dict[str, Any]],
    release: dict[str, Any],
) -> tuple[Path, Path | None]:
    research = vault / "Research"
    research.mkdir(parents=True, exist_ok=True)
    target = research / release["folder_name"]
    prepared = research / f".{release['folder_name']}.publish-{uuid.uuid4().hex}"
    if not _inside(prepared, research):
        raise ContractError("Prepared publish directory escaped Research")
    _prepare_directory(
        staging_dir=staging_dir,
        prepared=prepared,
        artifacts=artifacts,
        canonical_manifest=release["manifest"],
        canonical_decisions=release["decisions"],
    )

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


def main() -> None:
    args = parser().parse_args()
    staging_dir = Path(args.staging_dir).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve()
    if not staging_dir.is_dir():
        raise SystemExit(f"Staging directory does not exist: {staging_dir}")
    if not vault.is_dir():
        raise SystemExit(f"Vault does not exist: {vault}")
    artifacts = _load_artifacts(args)
    release = validate_release(
        staging_dir=staging_dir,
        artifacts=artifacts,
        allow_degraded=args.allow_degraded,
    )
    backup_root = (
        Path(args.backup_root).expanduser().resolve()
        if args.backup_root
        else vault / ".local" / "deeppapernote" / "migration-backup" / release["run_id"]
    )
    target: Path | None = None
    backup: Path | None = None
    if not args.dry_run:
        target, backup = publish_transaction(
            staging_dir=staging_dir,
            vault=vault,
            backup_root=backup_root,
            artifacts=artifacts,
            release=release,
        )
    report = artifact_header(
        "publish_report",
        paper_id=release["paper_id"],
        run_id=release["run_id"],
        status="pass",
    )
    report.update(
        {
            "dry_run": args.dry_run,
            "note_sha256": release["note_sha256"],
            "target": str(target or (vault / "Research" / release["folder_name"])),
            "backup": str(backup) if backup else "",
            "materialized_figures": release["materialized"],
        }
    )
    emit_json(report, args.output or None)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Final publisher that requires a hash-bound figure visual review."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from contracts_v2 import artifact_header, emit_json, load_json_object, require_same_identity
from figure_visual_review_contracts_v2 import (
    canonical_json_sha256,
    validate_figure_visual_review,
)
from publish_note_v2 import publish_transaction, validate_release


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
    command.add_argument("--allow-degraded", action="store_true")
    command.add_argument("--dry-run", action="store_true")
    return command


def _load_release_artifacts(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
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
) -> dict[str, Any]:
    """Run the new gate before the legacy transactional publisher is entered."""
    manifest = artifacts["figure_manifest"]
    decisions = artifacts["figure_decisions"]
    validate_figure_visual_review(
        visual_review,
        manifest=manifest,
        decisions=decisions,
        contact_sheet=contact_sheet,
    )
    require_same_identity(
        visual_review,
        contact_sheet,
        *artifacts.values(),
    )
    return visual_review


def main() -> None:
    args = parser().parse_args()
    staging_dir = Path(args.staging_dir).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve()
    if not staging_dir.is_dir():
        raise SystemExit(f"Staging directory does not exist: {staging_dir}")
    if not vault.is_dir():
        raise SystemExit(f"Vault does not exist: {vault}")

    artifacts = _load_release_artifacts(args)
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
            "publisher": "publish_note_final_v2",
            "dry_run": args.dry_run,
            "note_sha256": release["note_sha256"],
            "figure_visual_review_sha256": canonical_json_sha256(visual_review),
            "figure_contact_sheet_sha256": canonical_json_sha256(contact_sheet),
            "target": str(target or (vault / "Research" / release["folder_name"])),
            "backup": str(backup) if backup else "",
            "materialized_figures": release["materialized"],
        }
    )
    emit_json(report, args.output or None)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate, archive, and atomically publish one schema-v2 paper note."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import uuid
import warnings
from pathlib import Path, PurePosixPath
from typing import Any

from build_synthesis_bundle_v2 import build_bundle
from contracts_v2 import (
    ContractError,
    artifact_header,
    canonical_json_sha256,
    emit_json,
    load_json_object,
    note_plan_bound_evidence_ids,
    require_note_hash,
    require_same_identity,
    require_v2_artifact,
    sha256_file,
    sha256_text,
    validate_evidence_pack_artifact,
    validate_note_plan_artifact,
    validate_paper_record_artifact,
    validate_review_artifact,
    validate_run_id,
)
from figure_contracts_v2 import (
    figure_note_alignment_issues,
    materialize_inserted_assets,
    normalize_figure_decisions,
    normalize_figure_manifest,
)
from figure_visual_review_contracts_v2 import validate_figure_visual_review
from lint_note_v2 import reader_visible_figure_metadata_issues
from rebuild_paper_navigation import write_navigation_atomic
from vault import (
    IMAGE_EXTENSIONS,
    LOCAL_PDF_LIBRARY_ROOT,
    NAVIGATION_PATH,
    NOTE_FILENAME,
    folder_title_matches,
    is_zotero_deleted_library_path,
    lint_vault,
    paper_local_image_names,
    parse_frontmatter,
    validate_frontmatter_properties,
    validate_image_file,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--staging-dir", required=True)
    command.add_argument("--vault", required=True)
    command.add_argument("--paper-record", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--synthesis-bundle", required=True)
    command.add_argument("--note-plan", required=True)
    command.add_argument("--lint", required=True)
    command.add_argument("--quality", required=True)
    command.add_argument("--readability", required=True)
    command.add_argument("--figure-manifest", required=True)
    command.add_argument("--figure-decisions", required=True)
    command.add_argument(
        "--figure-contact-sheet",
        default="",
        help="Required only when the staged note embeds a current-run image.",
    )
    command.add_argument(
        "--figure-visual-review",
        default="",
        help="Required only when the staged note embeds a current-run image.",
    )
    command.add_argument("--backup-root", default="")
    command.add_argument("--output", default="")
    return command

def _safe_folder_name(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip().rstrip(".")
    if not cleaned:
        raise ContractError("Canonical title becomes empty after removing invalid path characters")
    return cleaned


def _normalize_doi(value: object) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", text)


def _normalize_arxiv(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"^(?:arxiv:\s*|https?://arxiv\.org/(?:abs|pdf)/)", "", text)
    text = text.removesuffix(".pdf")
    return re.sub(r"v\d+$", "", text)


def _normalize_authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        " ".join(str(author).split()).casefold()
        for author in value
        if str(author).strip()
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _vault_pdf_path(value: object) -> PurePosixPath:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or len(path.parts) < 4
        or path.parts[0] != LOCAL_PDF_LIBRARY_ROOT
        or is_zotero_deleted_library_path(path)
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() != ".pdf"
    ):
        raise ContractError(
            "Formal publishing requires each document to be a Vault-relative PDF under "
            "\u6587\u732e/<collection>/<paper>/ outside Zotero\u5df2\u5220\u9664/"
        )
    return path


def _document_path_in_vault(
    *,
    vault: Path,
    document: dict[str, Any],
) -> tuple[Path, PurePosixPath]:
    relative = _vault_pdf_path(document.get("vault_path"))
    expected = (vault / Path(*relative.parts)).resolve()
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    if not _inside(expected, library):
        raise ContractError("Document Vault path escaped the \u6587\u732e/ library")
    local = Path(str(document.get("path", ""))).expanduser().resolve()
    if local != expected:
        raise ContractError("Document local path does not match its Vault-relative path")
    if not local.is_file():
        raise ContractError(f"Document PDF is missing: {relative.as_posix()}")
    return local, relative


def resolve_publish_target(
    *,
    vault: Path,
    paper_record: dict[str, Any],
    release: dict[str, Any],
) -> Path:
    """Derive and validate the Zotero-mirrored paper directory from local PDFs."""
    documents = paper_record["paper_record"].get("documents", [])
    main_documents = [
        document
        for document in documents
        if isinstance(document, dict) and document.get("role") == "main"
    ]
    if len(main_documents) != 1:
        raise ContractError("Formal publishing requires exactly one local main PDF")

    main_path, _ = _document_path_in_vault(
        vault=vault,
        document=main_documents[0],
    )
    target = main_path.parent
    if not target.is_dir() or not folder_title_matches(str(release["title"]), target.name):
        raise ContractError(
            "Main PDF must live in the canonical paper directory under \u6587\u732e/"
        )
    for document in documents:
        if not isinstance(document, dict):
            raise ContractError("paper_record documents must be objects")
        document_path, _ = _document_path_in_vault(vault=vault, document=document)
        if document_path.parent != target:
            raise ContractError(
                "Main PDF and supplementary PDFs must be stored in the same paper directory"
            )
    return target


def _pdf_hashes(target: Path) -> dict[str, str]:
    return {
        path.name: sha256_file(path)
        for path in sorted(target.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file() and path.suffix.casefold() == ".pdf"
    }


def _safe_remove_tree(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    if not _inside(resolved, allowed_root) or resolved == allowed_root.resolve():
        raise ContractError(
            f"Refusing recursive cleanup outside temporary publish root: {resolved}"
        )
    if resolved.exists():
        shutil.rmtree(resolved)


def validate_operational_paths(
    *,
    vault: Path,
    backup_root: Path,
    output: Path | None,
) -> None:
    """Keep rollback/report artifacts outside reader-facing and tracked Vault content."""
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    local_root = (vault / ".local").resolve()
    if _inside(backup_root, library):
        raise ContractError("backup_root must stay outside reader-facing \u6587\u732e/")
    if not _inside(backup_root, local_root):
        raise ContractError("backup_root must stay under .local/")
    if output is None or not _inside(output, vault):
        return
    if not _inside(output, local_root):
        raise ContractError("publish report output inside the Vault must stay under .local/")
    published_root = (local_root / "deeppapernote" / "published").resolve()
    if _inside(output, published_root):
        raise ContractError("publish report output must not overwrite any publish audit")


def validate_staging_path(*, vault: Path, staging_dir: Path, run_id: str) -> None:
    """Keep all mutable pre-publication content inside its current local run."""
    safe_run_id = validate_run_id(run_id)
    expected = (vault / ".local" / "deeppapernote" / "runs" / safe_run_id / "staging").resolve()
    if staging_dir.resolve() != expected:
        raise ContractError(
            "staging_dir must be the current run's .local/deeppapernote/runs/<run_id>/staging/"
        )


def _load_artifacts(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return {
        "paper_record": load_json_object(args.paper_record),
        "evidence_pack": load_json_object(args.evidence),
        "synthesis_bundle": load_json_object(args.synthesis_bundle),
        "note_plan": load_json_object(args.note_plan),
        "lint_report": load_json_object(args.lint),
        "quality_review": load_json_object(args.quality),
        "readability_review": load_json_object(args.readability),
        "figure_manifest": load_json_object(args.figure_manifest),
        "figure_decisions": load_json_object(args.figure_decisions),
    }


def validate_visual_review_for_publish(
    *,
    visual_review: dict[str, Any] | None,
    contact_sheet: dict[str, Any] | None,
    artifacts: dict[str, dict[str, Any]],
) -> None:
    """Require a visual review only for images that will actually be published."""
    manifest = artifacts["figure_manifest"]
    decisions = artifacts["figure_decisions"]
    inserted = any(
        isinstance(item, dict) and item.get("decision") == "inserted"
        for item in decisions.get("decisions", [])
    )
    if not inserted:
        if visual_review is not None or contact_sheet is not None:
            raise ContractError(
                "No embedded image exists, so no figure-review artifacts are allowed"
            )
        return
    if visual_review is None or contact_sheet is None:
        raise ContractError("Embedded images require a current-run contact sheet and visual review")
    validate_figure_visual_review(
        visual_review,
        manifest=manifest,
        decisions=decisions,
        contact_sheet=contact_sheet,
    )
    require_same_identity(visual_review, contact_sheet, *artifacts.values())

def _image_names(image_dir: Path) -> set[str]:
    if not image_dir.exists():
        return set()
    if not image_dir.is_dir():
        raise ContractError(f"images is not a directory: {image_dir}")
    return {item.name for item in image_dir.iterdir() if item.is_file()}


def validate_note_image_set(note_text: str, image_dir: Path, *, label: str) -> set[str]:
    """Require local image references and on-disk image files to match exactly."""
    referenced, failures = paper_local_image_names(note_text)
    actual = _image_names(image_dir)
    missing = sorted(referenced - actual)
    orphaned = sorted(actual - referenced)
    failures.extend(f"image_missing:{name}" for name in missing)
    failures.extend(f"image_orphan:{name}" for name in orphaned)
    for name in sorted(actual):
        corruption = validate_image_file(image_dir / name)
        if corruption:
            failures.append(f"image_corrupt:{name}:{corruption}")
    if failures:
        raise ContractError(f"{label} image release gate failed: " + "; ".join(failures))
    return actual


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
    if not has_inserted:
        return "none_needed"
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


def validate_synthesis_binding(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    context: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    """Rebuild and compare every deterministic synthesis field."""
    raw_decisions = context.get("figure_decisions")
    planned_decisions: dict[str, Any] = {}
    if isinstance(raw_decisions, dict) and raw_decisions:
        planned_decisions = normalize_figure_decisions(
            raw_decisions,
            manifest=manifest,
            require_final=False,
        )
        require_v2_artifact(
            planned_decisions,
            artifact_type="figure_decisions",
            allow_statuses={"pass"},
        )
        if canonical_json_sha256(planned_decisions) != canonical_json_sha256(raw_decisions):
            raise ContractError(
                "synthesis_bundle.figure_decisions is not a canonical validated artifact"
            )

    raw_assets = context.get("pdf_assets")
    assets: dict[str, Any] = {}
    if isinstance(raw_assets, dict) and raw_assets:
        assets = normalize_figure_manifest(raw_assets)
        require_v2_artifact(
            assets,
            artifact_type="figure_manifest",
            allow_statuses={"pass"},
        )
        if canonical_json_sha256(assets) != canonical_json_sha256(manifest):
            raise ContractError("synthesis_bundle.pdf_assets does not match figure_manifest")
    elif manifest.get("assets"):
        raise ContractError("synthesis_bundle.pdf_assets is missing current figure assets")

    expected = build_bundle(paper_record, evidence, planned_decisions, assets)
    for field in sorted(set(expected) | set(context)):
        if canonical_json_sha256(context.get(field)) != canonical_json_sha256(
            expected.get(field)
        ):
            raise ContractError(
                f"synthesis_bundle.{field} does not match validated source data"
            )
    return str(evidence["evidence_pack"]["paper_type"])


def validate_figure_sources(
    manifest: dict[str, Any],
    paper_record: dict[str, Any],
) -> None:
    documents = {
        str(document["document_id"]): document
        for document in paper_record["paper_record"]["documents"]
    }
    for index, asset in enumerate(manifest.get("assets", [])):
        document_id = str(asset.get("document_id", ""))
        document = documents.get(document_id)
        if document is None:
            raise ContractError(
                f"figure_manifest.assets[{index}] refers to unknown document {document_id!r}"
            )
        page_number = asset.get("page_number")
        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or not 1 <= page_number <= int(document["pages"])
        ):
            raise ContractError(
                f"figure_manifest.assets[{index}] page is outside its source document"
            )
        asset_role = str(asset.get("document_role", "")).strip()
        if asset_role and asset_role != document["role"]:
            raise ContractError(
                f"figure_manifest.assets[{index}] document_role does not match paper_record"
            )


def validate_figure_intent_decisions(
    note_plan: dict[str, Any], decisions: dict[str, Any]
) -> None:
    intents = note_plan["note_plan"].get("figure_intents", [])
    required = {
        str(item.get("target_id", "")).strip()
        for item in intents
        if isinstance(item, dict)
    }
    decided = {
        str(item.get("target_id", "")).strip()
        for item in decisions.get("decisions", [])
        if isinstance(item, dict)
    }
    missing = sorted(required - decided)
    if missing:
        raise ContractError(
            "note_plan figure intents lack final decisions: " + ", ".join(missing)
        )


def validate_release(
    *,
    staging_dir: Path,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    paper_record = artifacts["paper_record"]
    evidence = artifacts["evidence_pack"]
    context = artifacts["synthesis_bundle"]
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
    validate_evidence_pack_artifact(
        evidence,
        paper_record_artifact=paper_record,
        verify_files=True,
    )
    manifest = normalize_figure_manifest(artifacts["figure_manifest"], verify_files=True)
    validate_figure_sources(manifest, paper_record)
    require_v2_artifact(manifest, artifact_type="figure_manifest", allow_statuses={"pass"})
    require_v2_artifact(context, artifact_type="synthesis_bundle", allow_statuses={"pass"})
    paper_type = validate_synthesis_binding(paper_record, evidence, context, manifest)
    validate_note_plan_artifact(note_plan)
    validate_note_plan_evidence(note_plan, evidence)
    if note_plan["note_plan"]["paper_type"] != paper_type:
        raise ContractError(
            "note_plan.paper_type must match evidence_pack and synthesis_bundle paper_type"
        )
    require_v2_artifact(lint, artifact_type="lint_report", allow_statuses={"pass"})
    validate_review_artifact(quality, kind="quality", context=context)
    validate_review_artifact(readability, kind="readability", context=context, lint=lint)
    if str(quality["author"]).casefold() != str(readability["author"]).casefold():
        raise ContractError("Quality and readability reviews must name the same note author")

    decisions = normalize_figure_decisions(
        artifacts["figure_decisions"],
        manifest=manifest,
        require_final=True,
    )
    require_v2_artifact(manifest, artifact_type="figure_manifest", allow_statuses={"pass"})
    require_v2_artifact(decisions, artifact_type="figure_decisions", allow_statuses={"pass"})
    validate_figure_intent_decisions(note_plan, decisions)
    paper_id, run_id = require_same_identity(
        paper_record,
        evidence,
        context,
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
    referenced_images, image_reference_failures = paper_local_image_names(note_text)
    if image_reference_failures:
        raise ContractError(
            "Staging image references are invalid: " + "; ".join(image_reference_failures)
        )
    manifest_by_filename = {
        str(asset.get("filename", "")): asset
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict) and str(asset.get("filename", "")).strip()
    }
    unknown_images = sorted(referenced_images - set(manifest_by_filename))
    if unknown_images:
        raise ContractError(
            "Staging note references images absent from the current run manifest: "
            + ", ".join(unknown_images)
        )
    manifest_by_id = {
        str(asset.get("asset_id", "")): asset
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict) and str(asset.get("asset_id", "")).strip()
    }
    selected_images = {
        str(manifest_by_id[str(entry.get("selected_asset_id", ""))].get("filename", ""))
        for entry in decisions.get("decisions", [])
        if isinstance(entry, dict)
        and entry.get("decision") == "inserted"
        and str(entry.get("selected_asset_id", "")) in manifest_by_id
    }
    if referenced_images != selected_images:
        raise ContractError(
            "Staging image embeds do not match the current run's finalized selections"
        )
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
    if parsed.properties.get("paper_type") != paper_type:
        raise ContractError(
            "Frontmatter paper_type must match evidence, synthesis, and note plan"
        )
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
    image_names = validate_note_image_set(note_text, image_dir, label="Staging")
    materialized_names = {str(item["filename"]) for item in materialized}
    if image_names != materialized_names:
        raise ContractError(
            "Staging images must exactly match inserted, reviewed manifest assets"
        )

    metadata = paper_record["paper_record"]["metadata"]
    title = str(metadata.get("title", "")).strip()
    if parsed.properties.get("title") != title:
        raise ContractError("Frontmatter title must match paper_record metadata.title")
    doi = _normalize_doi(metadata.get("doi", ""))
    arxiv = _normalize_arxiv(metadata.get("arxiv_id") or metadata.get("arxiv", ""))
    if not doi and paper_id.casefold().startswith("doi:"):
        doi = _normalize_doi(paper_id)
    if not arxiv and paper_id.casefold().startswith("arxiv:"):
        arxiv = _normalize_arxiv(paper_id)
    return {
        "paper_id": paper_id,
        "run_id": run_id,
        "title": title,
        "folder_name": _safe_folder_name(title),
        "note_sha256": note_sha,
        "manifest": manifest,
        "decisions": decisions,
        "materialized": materialized,
        "image_names": sorted(image_names),
        "evidence_level": evidence_level,
        "figure_status": figure_status,
        "doi": doi,
        "arxiv": arxiv,
        "year": str(parsed.properties.get("year", "")).strip(),
        "authors": list(_normalize_authors(parsed.properties.get("authors", []))),
    }


def _prepare_directory(*, staging_dir: Path, prepared: Path) -> None:
    """Prepare only reader-facing Vault content."""
    prepared.mkdir(parents=True, exist_ok=False)
    note_text = (staging_dir / NOTE_FILENAME).read_text(encoding="utf-8")
    with (prepared / NOTE_FILENAME).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(note_text)
    image_dir = staging_dir / "images"
    if any(image_dir.iterdir()):
        shutil.copytree(image_dir, prepared / "images")


def validate_existing_target_identity(target: Path, release: dict[str, Any]) -> None:
    """Refuse to replace an unrelated paper whose sanitized folder name collides."""
    if not target.exists():
        return
    if not target.is_dir():
        raise ContractError(f"Existing paper target is not a directory: {target}")
    note_path = target / NOTE_FILENAME
    if not note_path.exists():
        return
    if not note_path.is_file():
        raise ContractError(f"Existing paper target has no regular {NOTE_FILENAME}: {target}")
    parsed = parse_frontmatter(note_path.read_text(encoding="utf-8-sig"))
    existing_title = str(parsed.properties.get("title", "")).strip()
    incoming_doi = _normalize_doi(release.get("doi", ""))
    existing_doi = _normalize_doi(parsed.properties.get("doi", ""))
    incoming_arxiv = _normalize_arxiv(release.get("arxiv", ""))
    existing_arxiv = _normalize_arxiv(parsed.properties.get("arxiv", ""))
    identifier_mismatch = bool(
        (incoming_doi and existing_doi and incoming_doi != existing_doi)
        or (incoming_arxiv and existing_arxiv and incoming_arxiv != existing_arxiv)
    )
    shared_identifier = bool(
        (incoming_doi and existing_doi and incoming_doi == existing_doi)
        or (incoming_arxiv and existing_arxiv and incoming_arxiv == existing_arxiv)
    )
    fallback_identity_mismatch = False
    if not shared_identifier:
        incoming_year = str(release.get("year", "")).strip()
        existing_year = str(parsed.properties.get("year", "")).strip()
        incoming_authors = _normalize_authors(release.get("authors", []))
        existing_authors = _normalize_authors(parsed.properties.get("authors", []))
        fallback_identity_mismatch = bool(
            not incoming_year
            or not existing_year
            or not incoming_authors
            or not existing_authors
            or incoming_year != existing_year
            or incoming_authors != existing_authors
        )
    if (
        parsed.errors
        or existing_title != release["title"]
        or identifier_mismatch
        or fallback_identity_mismatch
    ):
        raise ContractError(
            "Canonical title collides with an existing paper directory: "
            f"incoming={release['title']!r}, existing={existing_title or '<invalid>'!r}"
        )


def validate_published_target(target: Path, release: dict[str, Any]) -> None:
    """Recheck managed output while proving the source PDFs were left untouched."""
    note_path = target / NOTE_FILENAME
    if not note_path.is_file():
        raise ContractError(f"Published target is missing a regular {NOTE_FILENAME}")
    if "pdf_sha256" in release and _pdf_hashes(target) != release["pdf_sha256"]:
        raise ContractError("Published target changed one or more source PDFs")
    note_bytes = note_path.read_bytes()
    if b"\r" in note_bytes:
        raise ContractError("Published note must use LF line endings")
    note_text = note_bytes.decode("utf-8")
    if sha256_text(note_text) != release["note_sha256"]:
        raise ContractError("Published note hash differs from the validated staging note")
    image_names = validate_note_image_set(note_text, target / "images", label="Published")
    if image_names != set(release["image_names"]):
        raise ContractError("Published image set differs from the validated staging image set")
    expected_hashes = {
        str(item["filename"]): str(item["file_sha256"])
        for item in release.get("materialized", [])
    }
    for name, expected_hash in expected_hashes.items():
        if sha256_file(target / "images" / name) != expected_hash:
            raise ContractError(f"Published image hash mismatch: {name}")


def _remove_managed_content(target: Path, *, library: Path) -> None:
    note_path = target / NOTE_FILENAME
    if note_path.exists():
        if not note_path.is_file():
            raise ContractError(f"Managed note path is not a regular file: {note_path}")
        note_path.unlink()
    image_dir = target / "images"
    if image_dir.exists():
        if not image_dir.is_dir():
            raise ContractError(f"Managed images path is not a directory: {image_dir}")
        _safe_remove_tree(image_dir, allowed_root=library)


def _restore_managed_content(
    *,
    target: Path,
    backup: Path | None,
    library: Path,
) -> None:
    _remove_managed_content(target, library=library)
    if backup is None:
        return
    previous_note = backup / NOTE_FILENAME
    if previous_note.exists():
        os.replace(previous_note, target / NOTE_FILENAME)
    previous_images = backup / "images"
    if previous_images.exists():
        os.replace(previous_images, target / "images")


def publish_transaction(
    *,
    staging_dir: Path,
    vault: Path,
    target: Path,
    backup_root: Path,
    release: dict[str, Any],
) -> tuple[Path, Path | None]:
    validate_operational_paths(vault=vault, backup_root=backup_root, output=None)
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    target = target.resolve()
    if not target.is_dir() or not _inside(target, library):
        raise ContractError(
            "Publish target must be an existing paper directory under \u6587\u732e/"
        )
    validate_existing_target_identity(target, release)
    release["pdf_sha256"] = _pdf_hashes(target)
    backup_root.mkdir(parents=True, exist_ok=True)
    prepared = backup_root / f".{target.name}.publish-{uuid.uuid4().hex}"
    backup_target = backup_root / f"{target.name}.managed-{uuid.uuid4().hex}"
    if not _inside(prepared, backup_root) or not _inside(backup_target, backup_root):
        raise ContractError("Prepared publish paths escaped the rollback root")
    note_backed_up = False
    images_backed_up = False
    note_published = False
    images_published = False
    try:
        _prepare_directory(staging_dir=staging_dir, prepared=prepared)
        backup_target.mkdir(parents=False, exist_ok=False)
        previous_note = target / NOTE_FILENAME
        if previous_note.exists():
            if not previous_note.is_file():
                raise ContractError(f"Existing note is not a regular file: {previous_note}")
            os.replace(previous_note, backup_target / NOTE_FILENAME)
            note_backed_up = True
        previous_images = target / "images"
        if previous_images.exists():
            if not previous_images.is_dir():
                raise ContractError(f"Existing images path is not a directory: {previous_images}")
            os.replace(previous_images, backup_target / "images")
            images_backed_up = True

        os.replace(prepared / NOTE_FILENAME, target / NOTE_FILENAME)
        note_published = True
        prepared_images = prepared / "images"
        if prepared_images.exists():
            os.replace(prepared_images, target / "images")
            images_published = True
        _safe_remove_tree(prepared, allowed_root=backup_root)
    except Exception as exc:
        rollback_failures: list[str] = []
        try:
            if note_published:
                published_note = target / NOTE_FILENAME
                if published_note.exists():
                    published_note.unlink()
            if images_published:
                published_images = target / "images"
                if published_images.exists():
                    _safe_remove_tree(published_images, allowed_root=library)
            if note_backed_up:
                os.replace(backup_target / NOTE_FILENAME, target / NOTE_FILENAME)
            if images_backed_up:
                os.replace(backup_target / "images", target / "images")
        except Exception as rollback_exc:
            rollback_failures.append(str(rollback_exc))
        if prepared.exists():
            try:
                _safe_remove_tree(prepared, allowed_root=backup_root)
            except Exception as cleanup_exc:
                rollback_failures.append(str(cleanup_exc))
        if not rollback_failures and backup_target.exists():
            _safe_remove_tree(backup_target, allowed_root=backup_root)
        if rollback_failures:
            raise ContractError(
                "Publish transaction rollback was incomplete: " + "; ".join(rollback_failures)
            ) from exc
        raise
    return target, backup_target


def _audit_target(vault: Path, run_id: str) -> Path:
    safe_run_id = validate_run_id(run_id)
    return vault / ".local" / "deeppapernote" / "published" / safe_run_id


def validate_existing_audit_identity(audit_target: Path, release: dict[str, Any]) -> None:
    if not audit_target.exists():
        return
    snapshot_path = audit_target / "snapshot.json"
    try:
        snapshot = load_json_object(snapshot_path)
        require_v2_artifact(
            snapshot,
            artifact_type="published_audit",
            allow_statuses={"pass"},
        )
    except Exception as exc:
        raise ContractError(f"Existing publish audit is unreadable: {snapshot_path}") from exc
    if (
        snapshot.get("paper_id") != release["paper_id"]
        or snapshot.get("run_id") != release["run_id"]
    ):
        raise ContractError(
            "run_id collides with an existing publish audit for another paper or run"
        )


def _replace_bytes_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}"
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _restore_navigation(vault: Path, previous: bytes | None) -> None:
    target = vault / NAVIGATION_PATH
    if previous is None:
        target.unlink(missing_ok=True)
    else:
        _replace_bytes_atomic(target, previous)


def archive_publish_audit(
    *,
    vault: Path,
    target: Path,
    artifacts: dict[str, dict[str, Any]],
    contact_sheet: dict[str, Any] | None,
    visual_review: dict[str, Any] | None,
    release: dict[str, Any],
    report: dict[str, Any],
) -> Path:
    """Write a compact JSON-only audit outside the reader-facing paper library."""
    audit_target = _audit_target(vault, release["run_id"])
    validate_existing_audit_identity(audit_target, release)
    audit_root = audit_target.parent
    audit_root.mkdir(parents=True, exist_ok=True)
    temporary = audit_root / f".{release['run_id']}.audit-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for name, artifact in artifacts.items():
            emit_json(artifact, temporary / f"{name}.json")
        if contact_sheet is not None:
            emit_json(contact_sheet, temporary / "figure_contact_sheet.json")
        if visual_review is not None:
            emit_json(visual_review, temporary / "figure_visual_review.json")
        emit_json(report, temporary / "publish_report.json")
        image_records = []
        image_dir = target / "images"
        images = image_dir.iterdir() if image_dir.is_dir() else ()
        for image in sorted(images, key=lambda item: item.name.casefold()):
            if image.is_file() and image.suffix.lower() in IMAGE_EXTENSIONS:
                image_records.append(
                    {
                        "name": image.name,
                        "sha256": sha256_file(image),
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
                "note": (target / NOTE_FILENAME).relative_to(vault).as_posix(),
                "note_sha256": release["note_sha256"],
                "note_file_sha256": sha256_file(target / NOTE_FILENAME),
                "images": image_records,
                "artifact_files": sorted(path.name for path in temporary.glob("*.json")),
                "contact_sheet_sha256": (
                    canonical_json_sha256(contact_sheet) if contact_sheet is not None else ""
                ),
                "visual_review_sha256": (
                    canonical_json_sha256(visual_review) if visual_review is not None else ""
                ),
                "navigation_sha256": report["navigation_sha256"],
                "vault_lint_summary": report["vault_lint_summary"],
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
            try:
                _safe_remove_tree(previous, allowed_root=audit_root)
            except Exception as exc:
                warnings.warn(
                    "Published audit succeeded, but the old audit backup could not be "
                    f"removed: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
    except Exception:
        if temporary.exists():
            _safe_remove_tree(temporary, allowed_root=audit_root)
        raise
    return audit_target


def _rollback_after_audit_failure(
    *, target: Path, backup: Path | None, vault: Path
) -> None:
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    if not target.exists() or not _inside(target, library):
        raise ContractError("Cannot roll back a target outside the \u6587\u732e/ paper library")
    _restore_managed_content(target=target, backup=backup, library=library)
    if backup and backup.exists() and not any(backup.iterdir()):
        backup.rmdir()


def _rollback_release_state(
    *,
    target: Path,
    backup: Path | None,
    vault: Path,
    previous_navigation: bytes | None,
) -> None:
    failures: list[str] = []
    try:
        _rollback_after_audit_failure(target=target, backup=backup, vault=vault)
    except Exception as exc:
        failures.append(f"note:{exc}")
    try:
        _restore_navigation(vault, previous_navigation)
    except Exception as exc:
        failures.append(f"navigation:{exc}")
    if failures:
        raise ContractError("Release rollback was incomplete: " + "; ".join(failures))


def main() -> None:
    args = parser().parse_args()
    staging_dir = Path(args.staging_dir).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve()
    if not staging_dir.is_dir():
        raise SystemExit(f"Staging directory does not exist: {staging_dir}")
    if not vault.is_dir():
        raise SystemExit(f"Vault does not exist: {vault}")

    artifacts = _load_artifacts(args)
    run_id = str(artifacts["paper_record"].get("run_id", ""))
    validate_staging_path(vault=vault, staging_dir=staging_dir, run_id=run_id)
    release = validate_release(
        staging_dir=staging_dir,
        artifacts=artifacts,
    )
    contact_sheet = (
        load_json_object(args.figure_contact_sheet) if args.figure_contact_sheet else None
    )
    visual_review = (
        load_json_object(args.figure_visual_review) if args.figure_visual_review else None
    )
    validate_visual_review_for_publish(
        visual_review=visual_review,
        contact_sheet=contact_sheet,
        artifacts=artifacts,
    )
    backup_root = (
        Path(args.backup_root).expanduser().resolve()
        if args.backup_root
        else vault / ".local" / "deeppapernote" / "rollback" / release["run_id"]
    )
    report_output = Path(args.output).expanduser().resolve() if args.output else None
    validate_operational_paths(
        vault=vault,
        backup_root=backup_root,
        output=report_output,
    )
    predicted_target = resolve_publish_target(
        vault=vault,
        paper_record=artifacts["paper_record"],
        release=release,
    )
    predicted_audit = _audit_target(vault, release["run_id"])
    validate_existing_audit_identity(predicted_audit, release)
    navigation_path = vault / NAVIGATION_PATH
    previous_navigation = navigation_path.read_bytes() if navigation_path.exists() else None

    report = artifact_header(
        "publish_report",
        paper_id=release["paper_id"],
        run_id=release["run_id"],
        status="pass",
    )
    report.update(
        {
            "publisher": "publish_note_v2",
            "note_sha256": release["note_sha256"],
            "figure_visual_review_sha256": (
                canonical_json_sha256(visual_review) if visual_review is not None else ""
            ),
            "figure_contact_sheet_sha256": (
                canonical_json_sha256(contact_sheet) if contact_sheet is not None else ""
            ),
            "target": str(predicted_target),
            "audit": str(predicted_audit),
            "backup": "",
            "materialized_figures": release["materialized"],
            "evidence_level": release["evidence_level"],
            "figure_status": release["figure_status"],
        }
    )

    target, backup = publish_transaction(
        staging_dir=staging_dir,
        vault=vault,
        target=predicted_target,
        backup_root=backup_root,
        release=release,
    )
    report["backup"] = str(backup) if backup else ""
    try:
        validate_published_target(target, release)
        navigation = write_navigation_atomic(vault)
        vault_lint = lint_vault(vault)
        if vault_lint["status"] != "pass":
            summary = vault_lint["summary"]
            raise ContractError(
                "Strict Vault lint failed after publication: "
                f"errors={summary['errors']}, warnings={summary['warnings']}"
            )
        navigation_sha256 = sha256_file(navigation)
        lint_summary = dict(vault_lint["summary"])
        report.update(
            {
                "navigation": str(navigation),
                "navigation_sha256": navigation_sha256,
                "vault_lint_status": "pass",
                "vault_lint_summary": lint_summary,
                "completion": {
                    "navigation_sha256": navigation_sha256,
                    "vault_lint_status": "pass",
                    "vault_lint_summary": lint_summary,
                },
            }
        )
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
    except Exception as exc:
        try:
            _rollback_release_state(
                target=target,
                backup=backup,
                vault=vault,
                previous_navigation=previous_navigation,
            )
        except Exception as rollback_exc:
            raise ContractError(str(rollback_exc)) from exc
        raise

    if backup and backup.exists():
        try:
            _safe_remove_tree(backup, allowed_root=backup_root)
        except Exception as exc:
            warnings.warn(
                f"Publication completed, but the note backup could not be removed: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    if backup_root.exists():
        try:
            if not any(backup_root.iterdir()):
                backup_root.rmdir()
        except OSError as exc:
            warnings.warn(
                f"Publication completed, but the empty rollback directory remains: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    try:
        emit_json(report, report_output)
    except OSError as exc:
        warnings.warn(
            f"Publication completed, but the requested report output could not be written: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        if report_output is not None:
            emit_json(report)


if __name__ == "__main__":
    main()

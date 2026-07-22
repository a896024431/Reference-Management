#!/usr/bin/env python3
"""Finalize one run-local, text-only DeepPaperNote publication by run ID."""

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
    validate_run_id,
    validate_second_review_artifact,
)
from lint_note_v2 import build_final_lint
from rebuild_paper_navigation import write_navigation_atomic
from record_second_review_v2 import build_second_review_artifact
from vault import (
    LOCAL_PDF_LIBRARY_ROOT,
    NAVIGATION_PATH,
    NOTE_FILENAME,
    folder_title_matches,
    is_zotero_deleted_library_path,
    parse_frontmatter,
    validate_frontmatter_properties,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--vault", required=True)
    command.add_argument("--run-id", required=True)
    command.add_argument("--author", required=True, help="Identity of the note author.")
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
    return re.sub(r"v\d+$", "", text.removesuffix(".pdf"))


def _normalize_authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        " ".join(str(author).split()).casefold() for author in value if str(author).strip()
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
            "文献/<collection>/<paper>/ outside Zotero已删除/"
        )
    return path


def _document_path_in_vault(*, vault: Path, document: dict[str, Any]) -> tuple[Path, PurePosixPath]:
    relative = _vault_pdf_path(document.get("vault_path"))
    expected = (vault / Path(*relative.parts)).resolve()
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    if not _inside(expected, library):
        raise ContractError("Document Vault path escaped the 文献/ library")
    local = Path(str(document.get("path", ""))).expanduser().resolve()
    if local != expected:
        raise ContractError("Document local path does not match its Vault-relative path")
    if not local.is_file():
        raise ContractError(f"Document PDF is missing: {relative.as_posix()}")
    return local, relative


def _pdf_hashes(target: Path) -> dict[str, str]:
    return {
        path.name: sha256_file(path)
        for path in sorted(target.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file() and path.suffix.casefold() == ".pdf"
    }


def resolve_publish_target(
    *, vault: Path, paper_record: dict[str, Any], release: dict[str, Any]
) -> Path:
    documents = paper_record["paper_record"].get("documents", [])
    main_documents = [
        document
        for document in documents
        if isinstance(document, dict) and document.get("role") == "main"
    ]
    if len(main_documents) != 1:
        raise ContractError("Formal publishing requires exactly one local main PDF")
    main_path, _ = _document_path_in_vault(vault=vault, document=main_documents[0])
    target = main_path.parent
    if not target.is_dir() or not folder_title_matches(str(release["title"]), target.name):
        raise ContractError("Main PDF must live in the canonical paper directory under 文献/")
    for document in documents:
        if not isinstance(document, dict):
            raise ContractError("paper_record documents must be objects")
        document_path, _ = _document_path_in_vault(vault=vault, document=document)
        if document_path.parent != target:
            raise ContractError("Main PDF and supplementary PDFs must share one paper directory")
    return target


def _safe_remove_tree(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    if not _inside(resolved, allowed_root) or resolved == allowed_root.resolve():
        raise ContractError(
            f"Refusing recursive cleanup outside temporary publish root: {resolved}"
        )
    if resolved.exists():
        shutil.rmtree(resolved)


def validate_operational_paths(*, vault: Path, backup_root: Path, output: Path | None) -> None:
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    local_root = (vault / ".local").resolve()
    if _inside(backup_root, library) or not _inside(backup_root, local_root):
        raise ContractError("backup_root must stay under .local/ and outside reader-facing 文献/")
    if output is not None and _inside(output, vault) and not _inside(output, local_root):
        raise ContractError("publish report output inside the Vault must stay under .local/")


def _run_directory(vault: Path, run_id: str) -> Path:
    safe_run_id = validate_run_id(run_id)
    run_dir = (vault / ".local" / "deeppapernote" / "runs" / safe_run_id).resolve()
    if not run_dir.is_dir():
        raise ContractError(f"DeepPaperNote run does not exist: {run_dir}")
    return run_dir


def _load_run_artifacts(run_dir: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "paper_record": run_dir / "paper_record.json",
        "evidence_pack": run_dir / "evidence_pack.json",
        "visual_pages": run_dir / "visual_pages.json",
        "synthesis_bundle": run_dir / "synthesis_bundle.json",
        "note_plan": run_dir / "note_plan.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ContractError("Run is missing required artifacts: " + ", ".join(missing))
    return {name: load_json_object(path) for name, path in paths.items()}


def _validate_staging(staging_dir: Path) -> Path:
    if not staging_dir.is_dir():
        raise ContractError(f"Staging directory does not exist: {staging_dir}")
    entries = {item.name for item in staging_dir.iterdir()}
    if entries != {NOTE_FILENAME}:
        raise ContractError("Text-only staging must contain only 笔记.md")
    note_path = staging_dir / NOTE_FILENAME
    if not note_path.is_file():
        raise ContractError("Staging note is not a regular file")
    return note_path


def validate_note_plan_evidence(note_plan: dict[str, Any], evidence: dict[str, Any]) -> None:
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
        raise ContractError("note_plan references unknown evidence: " + ", ".join(unknown))


def validate_synthesis_binding(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    visual_pages: dict[str, Any],
    context: dict[str, Any],
) -> str:
    require_v2_artifact(visual_pages, artifact_type="visual_pages", allow_statuses={"pass"})
    expected = build_bundle(paper_record, evidence, visual_pages)
    for field in sorted(set(expected) | set(context)):
        if canonical_json_sha256(context.get(field)) != canonical_json_sha256(expected.get(field)):
            raise ContractError(f"synthesis_bundle.{field} does not match validated source data")
    return str(evidence["evidence_pack"]["paper_type"])


def _image_markup_present(note_text: str) -> bool:
    return bool(re.search(r"!\[|<img\b", note_text, flags=re.IGNORECASE))


def expected_evidence_level(paper_record: dict[str, Any]) -> str:
    documents = paper_record["paper_record"].get("documents", [])
    if not any(
        document.get("role") == "main" for document in documents if isinstance(document, dict)
    ):
        raise ContractError("Formal publishing requires one parsed main document")
    return (
        "full_text_supplement"
        if any(
            document.get("role") == "supplement"
            for document in documents
            if isinstance(document, dict)
        )
        else "full_text"
    )


def validate_release(
    *,
    staging_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    lint: dict[str, Any],
    second_review: dict[str, Any],
) -> dict[str, Any]:
    paper_record = artifacts["paper_record"]
    evidence = artifacts["evidence_pack"]
    visual_pages = artifacts["visual_pages"]
    context = artifacts["synthesis_bundle"]
    note_plan = artifacts["note_plan"]
    validate_paper_record_artifact(paper_record)
    require_v2_artifact(paper_record, artifact_type="paper_record", allow_statuses={"pass"})
    validate_evidence_pack_artifact(evidence, paper_record_artifact=paper_record, verify_files=True)
    require_v2_artifact(context, artifact_type="synthesis_bundle", allow_statuses={"pass"})
    paper_type = validate_synthesis_binding(paper_record, evidence, visual_pages, context)
    validate_note_plan_artifact(note_plan)
    validate_note_plan_evidence(note_plan, evidence)
    if note_plan["note_plan"]["paper_type"] != paper_type:
        raise ContractError("note_plan.paper_type must match evidence and synthesis")
    require_v2_artifact(lint, artifact_type="lint_report", allow_statuses={"pass"})

    note_path = _validate_staging(staging_dir)
    note_text = note_path.read_text(encoding="utf-8")
    if _image_markup_present(note_text):
        raise ContractError("Text-only notes must not embed images")
    validate_second_review_artifact(second_review, context=context, note_text=note_text)
    paper_id, run_id = require_same_identity(
        paper_record,
        evidence,
        visual_pages,
        context,
        note_plan,
        lint,
        second_review,
    )
    note_sha = require_note_hash(note_text, lint, second_review)
    parsed = parse_frontmatter(note_text)
    frontmatter_issues = validate_frontmatter_properties(parsed.properties)
    if parsed.errors or frontmatter_issues:
        codes = [*parsed.errors, *(item["code"] for item in frontmatter_issues)]
        raise ContractError("Frontmatter release gate failed: " + ", ".join(codes))
    if parsed.properties.get("note_status") != "polished":
        raise ContractError("Formal publishing requires note_status: polished")
    if parsed.properties.get("paper_type") != paper_type:
        raise ContractError("Frontmatter paper_type must match evidence and synthesis")
    evidence_level = expected_evidence_level(paper_record)
    if parsed.properties.get("evidence_level") != evidence_level:
        raise ContractError(f"Frontmatter evidence_level must be {evidence_level!r}")

    metadata = paper_record["paper_record"]["metadata"]
    title = str(metadata.get("title", "")).strip()
    if parsed.properties.get("title") != title:
        raise ContractError("Frontmatter title must match paper_record metadata.title")
    doi = _normalize_doi(metadata.get("doi", ""))
    arxiv = _normalize_arxiv(metadata.get("arxiv_id") or metadata.get("arxiv", ""))
    return {
        "paper_id": paper_id,
        "run_id": run_id,
        "title": title,
        "folder_name": _safe_folder_name(title),
        "note_sha256": note_sha,
        "evidence_level": evidence_level,
        "doi": doi,
        "arxiv": arxiv,
        "year": str(parsed.properties.get("year", "")).strip(),
        "authors": list(_normalize_authors(parsed.properties.get("authors", []))),
    }


def validate_existing_target_identity(target: Path, release: dict[str, Any]) -> None:
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
    shared_identifier = bool(
        (incoming_doi and existing_doi and incoming_doi == existing_doi)
        or (incoming_arxiv and existing_arxiv and incoming_arxiv == existing_arxiv)
    )
    identifier_mismatch = bool(
        (incoming_doi and existing_doi and incoming_doi != existing_doi)
        or (incoming_arxiv and existing_arxiv and incoming_arxiv != existing_arxiv)
    )
    fallback_mismatch = False
    if not shared_identifier:
        fallback_mismatch = (
            not release.get("year")
            or str(parsed.properties.get("year", "")).strip() != release["year"]
            or not release.get("authors")
            or _normalize_authors(parsed.properties.get("authors", [])) != tuple(release["authors"])
        )
    if (
        parsed.errors
        or existing_title != release["title"]
        or identifier_mismatch
        or fallback_mismatch
    ):
        raise ContractError(
            "Canonical title collides with an existing paper directory: "
            f"incoming={release['title']!r}, existing={existing_title or '<invalid>'!r}"
        )


def _prepare_note(*, staging_dir: Path, prepared: Path) -> None:
    prepared.mkdir(parents=True, exist_ok=False)
    note_text = (staging_dir / NOTE_FILENAME).read_text(encoding="utf-8")
    with (prepared / NOTE_FILENAME).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(note_text)


def _remove_managed_note(target: Path) -> None:
    note_path = target / NOTE_FILENAME
    if note_path.exists():
        if not note_path.is_file():
            raise ContractError(f"Managed note path is not a regular file: {note_path}")
        note_path.unlink()


def _restore_managed_note(*, target: Path, backup: Path | None) -> None:
    _remove_managed_note(target)
    if backup is None:
        return
    previous_note = backup / NOTE_FILENAME
    if previous_note.exists():
        os.replace(previous_note, target / NOTE_FILENAME)


def publish_transaction(
    *, staging_dir: Path, vault: Path, target: Path, backup_root: Path, release: dict[str, Any]
) -> tuple[Path, Path | None]:
    validate_operational_paths(vault=vault, backup_root=backup_root, output=None)
    library = (vault / LOCAL_PDF_LIBRARY_ROOT).resolve()
    target = target.resolve()
    if not target.is_dir() or not _inside(target, library):
        raise ContractError("Publish target must be an existing paper directory under 文献/")
    validate_existing_target_identity(target, release)
    release["pdf_sha256"] = _pdf_hashes(target)
    backup_root.mkdir(parents=True, exist_ok=True)
    prepared = backup_root / f".{target.name}.publish-{uuid.uuid4().hex}"
    backup_target = backup_root / f"{target.name}.managed-{uuid.uuid4().hex}"
    note_backed_up = note_published = False
    try:
        _prepare_note(staging_dir=staging_dir, prepared=prepared)
        backup_target.mkdir(parents=False, exist_ok=False)
        previous_note = target / NOTE_FILENAME
        if previous_note.exists():
            os.replace(previous_note, backup_target / NOTE_FILENAME)
            note_backed_up = True
        os.replace(prepared / NOTE_FILENAME, target / NOTE_FILENAME)
        note_published = True
        _safe_remove_tree(prepared, allowed_root=backup_root)
    except Exception:
        failures: list[str] = []
        try:
            if note_published and (target / NOTE_FILENAME).exists():
                (target / NOTE_FILENAME).unlink()
            if note_backed_up:
                os.replace(backup_target / NOTE_FILENAME, target / NOTE_FILENAME)
        except Exception as exc:
            failures.append(str(exc))
        if prepared.exists():
            try:
                _safe_remove_tree(prepared, allowed_root=backup_root)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise ContractError(
                "Publish transaction rollback was incomplete: " + "; ".join(failures)
            )
        raise
    return target, backup_target


def validate_published_target(target: Path, release: dict[str, Any]) -> None:
    note_path = target / NOTE_FILENAME
    if not note_path.is_file():
        raise ContractError(f"Published target is missing a regular {NOTE_FILENAME}")
    if _pdf_hashes(target) != release["pdf_sha256"]:
        raise ContractError("Published target changed one or more source PDFs")
    note_bytes = note_path.read_bytes()
    if b"\r" in note_bytes:
        raise ContractError("Published note must use LF line endings")
    if sha256_text(note_bytes.decode("utf-8")) != release["note_sha256"]:
        raise ContractError("Published note hash differs from the validated staging note")


def _audit_target(vault: Path, run_id: str) -> Path:
    return vault / ".local" / "deeppapernote" / "published" / validate_run_id(run_id)


def _replace_bytes_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


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
    release: dict[str, Any],
    report: dict[str, Any],
) -> Path:
    audit_target = _audit_target(vault, release["run_id"])
    audit_root = audit_target.parent
    audit_root.mkdir(parents=True, exist_ok=True)
    temporary = audit_root / f".{release['run_id']}.audit-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for name, artifact in artifacts.items():
            emit_json(artifact, temporary / f"{name}.json")
        emit_json(report, temporary / "publish_report.json")
        snapshot = artifact_header(
            "published_audit", paper_id=release["paper_id"], run_id=release["run_id"], status="pass"
        )
        snapshot.update(
            {
                "note": (target / NOTE_FILENAME).relative_to(vault).as_posix(),
                "note_sha256": release["note_sha256"],
                "note_file_sha256": sha256_file(target / NOTE_FILENAME),
                "artifact_files": sorted(path.name for path in temporary.glob("*.json")),
                "navigation_sha256": report["navigation_sha256"],
                "target_lint_status": "pass",
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
                    f"Publication audit completed, but the old audit backup remains: {exc}",
                    RuntimeWarning,
                )
    except Exception:
        if temporary.exists():
            _safe_remove_tree(temporary, allowed_root=audit_root)
        raise
    return audit_target


def _rollback_release_state(
    *, target: Path, backup: Path | None, vault: Path, previous_navigation: bytes | None
) -> None:
    failures: list[str] = []
    try:
        _restore_managed_note(target=target, backup=backup)
    except Exception as exc:
        failures.append(f"note:{exc}")
    try:
        _restore_navigation(vault, previous_navigation)
    except Exception as exc:
        failures.append(f"navigation:{exc}")
    if failures:
        raise ContractError("Release rollback was incomplete: " + "; ".join(failures))


def finalize_run(
    *, vault: Path, run_id: str, author: str, backup_root: Path, output: Path | None
) -> dict[str, Any]:
    run_dir = _run_directory(vault, run_id)
    artifacts = _load_run_artifacts(run_dir)
    if str(artifacts["paper_record"].get("run_id", "")) != run_id:
        raise ContractError("run-id does not match paper_record")
    staging_dir = run_dir / "staging"
    note_path = _validate_staging(staging_dir)
    note_text = note_path.read_text(encoding="utf-8")
    lint = build_final_lint(note_text, artifacts["synthesis_bundle"], input_path=str(note_path))
    emit_json(lint, run_dir / "lint.json")
    require_v2_artifact(lint, artifact_type="lint_report", allow_statuses={"pass"})
    review_source_path = run_dir / "second_review.input.json"
    if not review_source_path.is_file():
        raise ContractError("Run is missing second_review.input.json")
    second_review = build_second_review_artifact(
        author=author,
        note_text=note_text,
        review_source=load_json_object(review_source_path),
        context=artifacts["synthesis_bundle"],
    )
    emit_json(second_review, run_dir / "second_review.json")
    require_v2_artifact(second_review, artifact_type="second_review", allow_statuses={"pass"})
    artifacts["lint_report"] = lint
    artifacts["second_review"] = second_review
    release = validate_release(
        staging_dir=staging_dir,
        artifacts=artifacts,
        lint=lint,
        second_review=second_review,
    )
    target = resolve_publish_target(
        vault=vault, paper_record=artifacts["paper_record"], release=release
    )
    navigation_path = vault / NAVIGATION_PATH
    previous_navigation = navigation_path.read_bytes() if navigation_path.exists() else None
    report = artifact_header(
        "publish_report", paper_id=release["paper_id"], run_id=release["run_id"]
    )
    report.update(
        {
            "publisher": "publish_note_v2",
            "note_sha256": release["note_sha256"],
            "target": str(target),
            "audit": str(_audit_target(vault, release["run_id"])),
            "target_lint_status": "pass",
        }
    )
    target, backup = publish_transaction(
        staging_dir=staging_dir,
        vault=vault,
        target=target,
        backup_root=backup_root,
        release=release,
    )
    try:
        validate_published_target(target, release)
        navigation = write_navigation_atomic(vault)
        report["navigation"] = str(navigation)
        report["navigation_sha256"] = sha256_file(navigation)
        audit = archive_publish_audit(
            vault=vault,
            target=target,
            artifacts=artifacts,
            release=release,
            report=report,
        )
        report["audit"] = str(audit)
    except Exception as exc:
        _rollback_release_state(
            target=target,
            backup=backup,
            vault=vault,
            previous_navigation=previous_navigation,
        )
        raise exc
    if backup is not None and backup.exists():
        try:
            _safe_remove_tree(backup, allowed_root=backup_root)
        except Exception as exc:
            warnings.warn(f"Publication completed, but the backup remains: {exc}", RuntimeWarning)
    try:
        emit_json(report, output or run_dir / "publish_report.json")
    except OSError as exc:
        warnings.warn(
            f"Publication completed, but the final report could not be written: {exc}",
            RuntimeWarning,
        )
    return report


def main() -> None:
    args = parser().parse_args()
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"Vault does not exist: {vault}")
    run_id = validate_run_id(args.run_id)
    backup_root = (
        Path(args.backup_root).expanduser().resolve()
        if args.backup_root
        else vault / ".local" / "deeppapernote" / "rollback" / run_id
    )
    output = Path(args.output).expanduser().resolve() if args.output else None
    try:
        validate_operational_paths(vault=vault, backup_root=backup_root, output=output)
        report = finalize_run(
            vault=vault,
            run_id=run_id,
            author=args.author,
            backup_root=backup_root,
            output=output,
        )
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    if output is None:
        print(__import__("json").dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

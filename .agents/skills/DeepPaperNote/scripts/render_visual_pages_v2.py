#!/usr/bin/env python3
"""Render a small, run-local set of PDF pages for visual reading only."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import fitz
from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    require_v2_artifact,
    sha256_file,
    validate_evidence_pack_artifact,
    validate_paper_record_artifact,
)

DEFAULT_MAX_PAGES = 12


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--paper-record", required=True)
    command.add_argument("--evidence", required=True)
    command.add_argument("--run-dir", required=True)
    command.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    command.add_argument("--output", default="")
    return command


def _caption_pages(pack: dict[str, Any]) -> list[tuple[str, int, list[str]]]:
    grouped: dict[tuple[str, int], list[str]] = {}
    for item in pack.get("figure_captions", []):
        if not isinstance(item, dict):
            continue
        document_id = str(item.get("document_id", "")).strip()
        page = item.get("page")
        if not document_id or not isinstance(page, int) or page < 1:
            continue
        label = str(item.get("id", "")).strip()
        grouped.setdefault((document_id, page), []).append(label)
    return [(document_id, page, labels) for (document_id, page), labels in sorted(grouped.items())]


def _referenced_pages(pack: dict[str, Any]) -> list[tuple[str, int, list[str]]]:
    grouped: dict[tuple[str, int], list[str]] = {}
    for unit in pack.get("evidence_units", []):
        if not isinstance(unit, dict):
            continue
        references = unit.get("figure_refs", [])
        if not isinstance(references, list) or not references:
            continue
        document_id = str(unit.get("document_id", "")).strip()
        page = unit.get("page")
        if not document_id or not isinstance(page, int) or page < 1:
            continue
        grouped.setdefault((document_id, page), []).extend(
            str(reference).strip() for reference in references if str(reference).strip()
        )
    return [
        (document_id, page, list(dict.fromkeys(labels)))
        for (document_id, page), labels in sorted(grouped.items())
    ]


def render_visual_pages(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    *,
    run_dir: str | Path,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    if fitz is None:
        raise ContractError("PyMuPDF/fitz is required for visual page rendering")
    if max_pages < 0:
        raise ContractError("max_pages must be non-negative")
    validate_paper_record_artifact(paper_record)
    validate_evidence_pack_artifact(evidence, paper_record_artifact=paper_record)
    require_v2_artifact(paper_record, artifact_type="paper_record", allow_statuses={"pass"})
    require_v2_artifact(evidence, artifact_type="evidence_pack", allow_statuses={"pass"})
    paper_id, run_id = require_same_identity(paper_record, evidence)
    pack = evidence.get("evidence_pack")
    record = paper_record.get("paper_record")
    if not isinstance(pack, dict) or not isinstance(record, dict):
        raise ContractError("paper_record and evidence_pack payloads are required")

    resolved_run_dir = Path(run_dir).expanduser().resolve()
    if resolved_run_dir.name != run_id:
        raise ContractError("run-dir must be the current run_id directory")
    output_dir = resolved_run_dir / "visual-pages"
    if output_dir.exists():
        raise ContractError(f"visual page directory already exists: {output_dir}")

    documents = {
        str(document.get("document_id", "")): document
        for document in record.get("documents", [])
        if isinstance(document, dict) and str(document.get("document_id", "")).strip()
    }
    selected = _caption_pages(pack) or _referenced_pages(pack)
    if max_pages:
        selected = selected[:max_pages]
    output_dir.mkdir(parents=True, exist_ok=False)
    pages: list[dict[str, Any]] = []
    try:
        for index, (document_id, page_number, labels) in enumerate(selected, start=1):
            document = documents.get(document_id)
            if document is None:
                raise ContractError(f"visual page refers to unknown document: {document_id}")
            source = Path(str(document.get("path", ""))).expanduser().resolve()
            if not source.is_file():
                raise ContractError(f"visual page source is missing: {source}")
            expected_sha = str(document.get("sha256", ""))
            before_sha = sha256_file(source)
            if before_sha != expected_sha:
                raise ContractError(f"visual page source changed before reading: {document_id}")
            pdf = None
            try:
                pdf = fitz.open(source)
                if len(pdf) != document["pages"]:
                    raise ContractError(f"visual page source page count changed: {document_id}")
                if page_number > len(pdf):
                    raise ContractError(
                        f"visual page is outside source document: {document_id} p. {page_number}"
                    )
                page = pdf[page_number - 1]
                output = output_dir / (
                    f"visual-{index:02d}-{document_id.replace(':', '-')}-p{page_number:04d}.png"
                )
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                pixmap.save(output)
            finally:
                if pdf is not None:
                    pdf.close()
                after_sha = sha256_file(source)
                if after_sha != before_sha or after_sha != expected_sha:
                    raise ContractError(f"visual page source changed while reading: {document_id}")
            pages.append(
                {
                    "document_id": document_id,
                    "document_role": str(document.get("role", "")),
                    "page": page_number,
                    "labels": labels,
                    "path": output.relative_to(resolved_run_dir).as_posix(),
                }
            )
    except Exception:
        for path in output_dir.glob("*"):
            path.unlink(missing_ok=True)
        output_dir.rmdir()
        raise

    artifact = artifact_header("visual_pages", paper_id=paper_id, run_id=run_id)
    artifact.update(
        {
            "purpose": "temporary_visual_reading_only",
            "directory": output_dir.relative_to(resolved_run_dir).as_posix(),
            "pages": pages,
        }
    )
    return artifact


def main() -> None:
    args = parser().parse_args()
    try:
        artifact = render_visual_pages(
            load_json_object(args.paper_record),
            load_json_object(args.evidence),
            run_dir=args.run_dir,
            max_pages=args.max_pages,
        )
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    emit_json(artifact, args.output or None)


if __name__ == "__main__":
    main()

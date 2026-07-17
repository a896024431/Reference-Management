#!/usr/bin/env python3
"""Create a v2 paper record from explicit local main/SI paths without fuzzy lookup."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import fitz, paper_id_for_record
from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    sha256_file,
    stable_id,
    utc_run_id,
    validate_paper_record_artifact,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--input-record",
        required=True,
        help="JSON file or object with title and explicit documents.",
    )
    command.add_argument("--output", default="")
    command.add_argument("--run-id", default="")
    command.add_argument("--paper-id", default="")
    command.add_argument(
        "--vault-root", default="", help="Used only to derive safe vault-relative document paths."
    )
    return command


def _pages(path: Path) -> int:
    if fitz is None:
        return 0
    document = fitz.open(path)
    try:
        return len(document)
    finally:
        document.close()


def _vault_relative(path: Path, vault_root: Path | None) -> str:
    if vault_root is None:
        return ""
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return ""


def _document(path_value: str, *, role: str, vault_root: Path | None) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ContractError(f"Document does not exist: {path}")
    if path.suffix.lower() != ".pdf":
        raise ContractError(f"Document is not a PDF: {path}")
    digest = sha256_file(path)
    return {
        "document_id": stable_id("doc", role, digest),
        "role": role,
        "path": str(path),
        "vault_path": _vault_relative(path, vault_root),
        "url": "",
        "source": "explicit_local_record",
        "sha256": digest,
        "pages": _pages(path),
        "filename": path.name,
    }


def create_explicit_record(
    source: dict[str, Any],
    *,
    run_id: str,
    paper_id: str = "",
    vault_root: str = "",
) -> dict[str, Any]:
    title = str(source.get("title", "")).strip()
    if not title:
        raise ContractError("Explicit input record requires title")
    root = Path(vault_root).expanduser().resolve() if vault_root else None
    metadata_excluded = {
        "main_pdf",
        "local_pdf_path",
        "supplement_pdfs",
        "documents",
        "paper_id",
        "run_id",
        "schema_version",
        "artifact_type",
        "status",
        "failures",
    }
    metadata = {key: value for key, value in source.items() if key not in metadata_excluded}
    canonical_id = paper_id or str(source.get("paper_id", "")) or paper_id_for_record(metadata)

    entries: list[tuple[str, str]] = []
    supplied_documents = source.get("documents")
    if isinstance(supplied_documents, list):
        for item in supplied_documents:
            if not isinstance(item, dict):
                raise ContractError("documents entries must be objects")
            role = str(item.get("role", "")).strip()
            path = str(item.get("path", "")).strip()
            entries.append((role, path))
    else:
        main_pdf = str(source.get("main_pdf") or source.get("local_pdf_path") or "").strip()
        if main_pdf:
            entries.append(("main", main_pdf))
        supplements = source.get("supplement_pdfs", []) or []
        if not isinstance(supplements, list):
            raise ContractError("supplement_pdfs must be a list")
        entries.extend(("supplement", str(path)) for path in supplements if str(path).strip())
    if sum(1 for role, _ in entries if role == "main") != 1:
        raise ContractError("Explicit input record requires exactly one main document")
    if any(role not in {"main", "supplement"} for role, _ in entries):
        raise ContractError("Document role must be main or supplement")

    documents = [_document(path, role=role, vault_root=root) for role, path in entries]
    artifact = artifact_header("paper_record", paper_id=canonical_id, run_id=run_id)
    artifact["paper_record"] = {
        "paper_id": canonical_id,
        "metadata": metadata,
        "documents": documents,
    }
    validate_paper_record_artifact(artifact)
    return artifact


def main() -> None:
    args = parser().parse_args()
    artifact = create_explicit_record(
        load_json_object(args.input_record),
        run_id=args.run_id or utc_run_id(),
        paper_id=args.paper_id,
        vault_root=args.vault_root,
    )
    emit_json(artifact, args.output or None)


if __name__ == "__main__":
    main()

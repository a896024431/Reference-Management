#!/usr/bin/env python3
"""Create one schema-v2 record from PDFs already mirrored in this Vault."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import extract_local_pdf_hints, fitz, normalize_whitespace, paper_id_for_record
from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    sha256_file,
    stable_id,
    utc_run_id,
    validate_paper_record_artifact,
)

ARCHIVE_DIRECTORY = "Zotero已删除"
KEY_SUFFIX_RE = re.compile(r"\s+\[[A-Za-z0-9]{8}\]\s*$")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True, help="Mirrored local main PDF under 文献/.")
    command.add_argument("--supplement", action="append", default=[])
    command.add_argument("--vault-root", required=True)
    command.add_argument("--run-id", default="")
    command.add_argument("--output", default="")
    return command


def _page_count(path: Path) -> int:
    if fitz is None:
        raise ContractError("PyMuPDF/fitz is required to inspect PDF page counts")
    document = fitz.open(path)
    try:
        return len(document)
    finally:
        document.close()


def _mirrored_pdf(value: str, *, vault_root: Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    library = (vault_root / "文献").resolve()
    try:
        relative = path.relative_to(library)
    except ValueError as exc:
        raise ContractError(f"{label} must be a local PDF under 文献/: {path}") from exc
    if (
        not path.is_file()
        or path.suffix.casefold() != ".pdf"
        or len(relative.parts) < 3
        or relative.parts[0].casefold() == ARCHIVE_DIRECTORY.casefold()
    ):
        raise ContractError(
            f"{label} must be an active PDF in 文献/<collection>/<paper>/: {path}"
        )
    return path


def _paper_directory_title(path: Path) -> str:
    """Use the mirrored folder title when a child attachment has an opaque name."""
    return normalize_whitespace(KEY_SUFFIX_RE.sub("", path.parent.name))


def _document(path: Path, *, role: str, vault_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    digest = sha256_file(resolved)
    return {
        "document_id": stable_id("doc", role, digest),
        "role": role,
        "path": str(resolved),
        "vault_path": resolved.relative_to(vault_root).as_posix(),
        "url": "",
        "source": "local_mirrored_pdf",
        "sha256": digest,
        "pages": _page_count(resolved),
        "filename": resolved.name,
    }


def create_local_record(
    input_pdf: str,
    *,
    run_id: str,
    vault_root: str,
    supplements: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(vault_root).expanduser().resolve()
    if not root.is_dir() or not (root / "文献").is_dir():
        raise ContractError(f"Vault root must contain 文献/: {root}")

    main = _mirrored_pdf(input_pdf, vault_root=root, label="--input")
    seen = {main}
    supplement_paths: list[Path] = []
    for index, value in enumerate(supplements or [], start=1):
        supplement = _mirrored_pdf(value, vault_root=root, label=f"--supplement[{index}]")
        if supplement.parent != main.parent:
            raise ContractError("All supplementary PDFs must share the main PDF directory")
        if supplement in seen:
            raise ContractError("Main and supplementary PDFs must not be repeated")
        seen.add(supplement)
        supplement_paths.append(supplement)

    hints = extract_local_pdf_hints(main)
    title = normalize_whitespace(str(hints.get("title", "")))
    title_source = str(hints.get("title_source", "filename"))
    if title_source == "filename":
        title = _paper_directory_title(main) or title
        title_source = "paper_directory" if title else title_source
    if not title:
        raise ContractError(
            "Local main PDF and its mirrored paper directory did not provide a title"
        )

    metadata: dict[str, Any] = {
        "title": title,
        "title_source": title_source,
        "local_pdf_path": str(main),
        "metadata_sources": ["local_pdf"],
    }
    for key in ("doi", "arxiv_id"):
        value = str(hints.get(key, "")).strip()
        if value:
            metadata[key] = value

    paper_id = paper_id_for_record(metadata)
    artifact = artifact_header("paper_record", paper_id=paper_id, run_id=run_id)
    artifact["paper_record"] = {
        "paper_id": paper_id,
        "metadata": metadata,
        "documents": [
            _document(main, role="main", vault_root=root),
            *[
                _document(path, role="supplement", vault_root=root)
                for path in supplement_paths
            ],
        ],
    }
    validate_paper_record_artifact(artifact)
    return artifact


def main() -> None:
    args = parser().parse_args()
    try:
        artifact = create_local_record(
            args.input,
            run_id=args.run_id or utc_run_id(),
            vault_root=args.vault_root,
            supplements=args.supplement,
        )
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    emit_json(artifact, args.output or None)


if __name__ == "__main__":
    main()

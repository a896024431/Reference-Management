#!/usr/bin/env python3
"""Resolve, enrich, and attach main/supplement PDFs to one schema-v2 paper record."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import (
    enrich_metadata,
    extract_doi,
    extract_local_pdf_hints,
    fitz,
    http_get_bytes,
    infer_source_type,
    maybe_load_json_record,
    paper_id_for_record,
    resolve_reference,
    slugify_filename,
)
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
        "--stage",
        choices=("resolve", "explicit", "metadata", "fetch"),
        required=True,
    )
    command.add_argument(
        "--input",
        required=True,
        help=(
            "Raw reference for resolve, trusted local-document JSON for explicit, "
            "or a v2 paper_record artifact otherwise."
        ),
    )
    command.add_argument("--output", default="")
    command.add_argument("--run-id", default="")
    command.add_argument("--paper-id", default="")
    command.add_argument(
        "--supplement", action="append", default=[], help="Supplement PDF path or URL; repeatable."
    )
    command.add_argument("--dest-dir", default="", help="Download directory for fetch stage.")
    command.add_argument(
        "--vault-root", default="", help="Record local PDFs with a safe Vault-relative path."
    )
    command.add_argument(
        "--offline",
        action="store_true",
        help="Require local documents and disable metadata queries and URL downloads.",
    )
    return command


def new_paper_record(seed: dict[str, Any], *, run_id: str, paper_id: str = "") -> dict[str, Any]:
    canonical_id = paper_id or str(seed.get("paper_id", "")) or paper_id_for_record(seed)
    metadata = dict(seed)
    metadata.pop("status", None)
    metadata.pop("script", None)
    payload = artifact_header("paper_record", paper_id=canonical_id, run_id=run_id)
    payload["paper_record"] = {
        "paper_id": canonical_id,
        "metadata": metadata,
        "documents": [],
    }
    return payload


def resolve_stage(
    value: str,
    *,
    run_id: str,
    paper_id: str = "",
    offline: bool = False,
) -> dict[str, Any]:
    trusted = maybe_load_json_record(value)
    if trusted is not None:
        seed = dict(trusted)
    elif offline and infer_source_type(value) != "local_pdf":
        seed = {
            "status": "offline_source_requires_local_pdf",
            "source_type": infer_source_type(value),
            "source_url": str(value).strip(),
            "metadata_sources": ["offline_input"],
        }
    else:
        seed = resolve_reference(value)
    payload = new_paper_record(seed, run_id=run_id, paper_id=paper_id)
    resolution_status = str(seed.get("status", "ok"))
    title = str(payload["paper_record"]["metadata"].get("title", "")).strip()
    if resolution_status != "ok":
        payload["status"] = "fail"
        payload["failures"] = [f"paper_identity_{resolution_status}"]
    elif not title:
        payload["status"] = "fail"
        payload["failures"] = ["paper_identity_missing_title"]
    validate_paper_record_artifact(payload)
    return payload


def metadata_stage(artifact: dict[str, Any], *, offline: bool = False) -> dict[str, Any]:
    validate_paper_record_artifact(artifact)
    record = artifact["paper_record"]
    original_id = artifact["paper_id"]
    metadata = dict(record["metadata"])
    enriched = (
        metadata
        if offline or metadata.get("source_type") == "pdf_url"
        else enrich_metadata(metadata)
    )
    enriched["paper_id"] = original_id
    record["metadata"] = enriched
    if not str(enriched.get("title", "")).strip():
        artifact["status"] = "fail"
        artifact["failures"] = ["metadata_missing_title"]
    validate_paper_record_artifact(artifact)
    return artifact


def _page_count(path: Path) -> int:
    if fitz is None:
        raise ContractError("PyMuPDF/fitz is required to inspect PDF page counts")
    document = fitz.open(path)
    try:
        return len(document)
    finally:
        document.close()


def _vault_relative(path: Path, vault_root: Path | None) -> str:
    if vault_root is None:
        return ""
    try:
        return path.resolve().relative_to(vault_root.resolve()).as_posix()
    except ValueError:
        return ""


def _document(
    path: Path,
    *,
    role: str,
    source: str,
    url: str = "",
    vault_root: Path | None = None,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    digest = sha256_file(resolved)
    return {
        "document_id": stable_id("doc", role, digest),
        "role": role,
        "path": str(resolved),
        "vault_path": _vault_relative(resolved, vault_root),
        "url": url,
        "source": source,
        "sha256": digest,
        "pages": _page_count(resolved),
        "filename": resolved.name,
    }


def create_explicit_record(
    source: dict[str, Any],
    *,
    run_id: str,
    paper_id: str = "",
    vault_root: str = "",
    supplements: list[str] | None = None,
) -> dict[str, Any]:
    """Create a paper record from trusted local main and supplement paths."""
    title = str(source.get("title", "")).strip()
    if not title:
        raise ContractError("Explicit input record requires title")
    root = Path(vault_root).expanduser().resolve() if vault_root else None
    if root is not None and (not root.exists() or not root.is_dir()):
        raise ContractError(f"Vault root is not a directory: {root}")

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
            entries.append(
                (
                    str(item.get("role", "")).strip(),
                    str(item.get("path", "")).strip(),
                )
            )
    else:
        main_pdf = str(source.get("main_pdf") or source.get("local_pdf_path") or "").strip()
        if main_pdf:
            entries.append(("main", main_pdf))
        configured_supplements = source.get("supplement_pdfs", []) or []
        if not isinstance(configured_supplements, list):
            raise ContractError("supplement_pdfs must be a list")
        entries.extend(
            ("supplement", str(path))
            for path in configured_supplements
            if str(path).strip()
        )
    entries.extend(
        ("supplement", str(path)) for path in (supplements or []) if str(path).strip()
    )
    if sum(1 for role, _ in entries if role == "main") != 1:
        raise ContractError("Explicit input record requires exactly one main document")
    if any(role not in {"main", "supplement"} for role, _ in entries):
        raise ContractError("Document role must be main or supplement")
    if any(not path for _, path in entries):
        raise ContractError("Every explicit document requires a local path")

    documents: list[dict[str, Any]] = []
    for role, path_value in entries:
        path = Path(path_value).expanduser().resolve()
        if not path.is_file():
            raise ContractError(f"Document does not exist: {path}")
        if path.suffix.lower() != ".pdf":
            raise ContractError(f"Document is not a PDF: {path}")
        documents.append(
            _document(
                path,
                role=role,
                source="explicit_local_record",
                vault_root=root,
            )
        )
    artifact = artifact_header("paper_record", paper_id=canonical_id, run_id=run_id)
    artifact["paper_record"] = {
        "paper_id": canonical_id,
        "metadata": metadata,
        "documents": documents,
    }
    validate_paper_record_artifact(artifact)
    return artifact


def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def _download(url: str, dest_dir: Path, *, fallback_name: str) -> Path:
    parsed_name = Path(urlparse(url).path).name
    name = parsed_name if parsed_name.lower().endswith(".pdf") else fallback_name
    target = dest_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(http_get_bytes(url))
    return target


def _main_source(metadata: dict[str, Any], *, offline: bool = False) -> tuple[str, str]:
    local = str(metadata.get("local_pdf_path", "")).strip()
    if local and Path(local).expanduser().exists():
        return "local", local
    if offline:
        return "", ""
    for key in ("pdf_url", "source_url"):
        value = str(metadata.get(key, "")).strip()
        if value and (key == "pdf_url" or value.lower().endswith(".pdf")):
            return "url", value
    arxiv_id = str(metadata.get("arxiv_id", "")).strip()
    if arxiv_id:
        return "url", f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    doi = extract_doi(str(metadata.get("doi", "")))
    if doi:
        candidate = enrich_metadata({"doi": doi, "title": metadata.get("title", "")})
        pdf_url = str(candidate.get("pdf_url", "")).strip()
        if pdf_url:
            return "url", pdf_url
    return "", ""


def _materialize_source(
    value: str,
    *,
    dest_dir: Path,
    role: str,
    fallback_name: str,
) -> tuple[Path, str, str]:
    if _is_url(value):
        return _download(value, dest_dir, fallback_name=fallback_name), "downloaded", value
    path = Path(value).expanduser()
    if not path.exists() or not path.is_file():
        raise ContractError(f"PDF does not exist: {path}")
    if path.suffix.lower() != ".pdf":
        raise ContractError(f"Expected a PDF for {role}: {path}")
    return path.resolve(), "local", ""


def _refresh_direct_pdf_identity(
    artifact: dict[str, Any],
    pdf_path: Path,
) -> None:
    """Replace a URL filename placeholder with identity read from the downloaded PDF."""
    record = artifact["paper_record"]
    metadata = record["metadata"]
    if metadata.get("source_type") != "pdf_url":
        return
    hints = extract_local_pdf_hints(pdf_path)
    title = str(hints.get("title", "")).strip()
    if not title or hints.get("title_source") not in {"metadata", "first_page"}:
        raise ContractError(
            "Direct PDF URL did not expose a trustworthy title in PDF metadata or page text"
        )
    metadata["title"] = title
    for key in ("doi", "arxiv_id"):
        value = str(hints.get(key, "")).strip()
        if value:
            metadata[key] = value
    if str(artifact["paper_id"]).startswith(("title:", "paper:")):
        identity_metadata = dict(metadata)
        identity_metadata.pop("paper_id", None)
        canonical_id = paper_id_for_record(identity_metadata)
        artifact["paper_id"] = canonical_id
        record["paper_id"] = canonical_id
        metadata["paper_id"] = canonical_id


def fetch_stage(
    artifact: dict[str, Any],
    *,
    supplements: list[str],
    dest_dir: str = "",
    vault_root: str = "",
    offline: bool = False,
) -> dict[str, Any]:
    validate_paper_record_artifact(artifact)
    record = artifact["paper_record"]
    metadata = record["metadata"]
    target_dir = Path(dest_dir or ".local/deeppapernote/pdfs").expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    root = Path(vault_root).expanduser().resolve() if vault_root else None
    if root is not None and (not root.exists() or not root.is_dir()):
        raise ContractError(f"Vault root is not a directory: {root}")
    failures: list[str] = []
    documents: list[dict[str, Any]] = []

    source_kind, source_value = _main_source(metadata, offline=offline)
    if not source_kind:
        failures.append("offline_main_pdf_missing" if offline else "main_pdf_source_missing")
    elif offline and source_kind == "url":
        failures.append("offline_network_fetch_disabled:main")
    else:
        try:
            fallback = f"{slugify_filename(str(metadata.get('title') or artifact['paper_id']))}.pdf"
            main_path, source, url = _materialize_source(
                source_value,
                dest_dir=target_dir,
                role="main",
                fallback_name=fallback,
            )
            _refresh_direct_pdf_identity(artifact, main_path)
            documents.append(
                _document(main_path, role="main", source=source, url=url, vault_root=root)
            )
        except Exception as exc:
            failures.append(f"main_pdf_failed: {exc}")

    configured_supplements = metadata.get("supplement_pdfs", []) or []
    supplement_values = [
        str(item) for item in [*configured_supplements, *supplements] if str(item).strip()
    ]
    seen: set[str] = set()
    for index, value in enumerate(supplement_values, start=1):
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        if offline and _is_url(value):
            failures.append(f"offline_network_fetch_disabled:supplement[{index}]")
            continue
        try:
            path, source, url = _materialize_source(
                value,
                dest_dir=target_dir,
                role="supplement",
                fallback_name=f"supplement-{index}.pdf",
            )
            documents.append(
                _document(path, role="supplement", source=source, url=url, vault_root=root)
            )
        except Exception as exc:
            failures.append(f"supplement_pdf_failed[{index}]: {exc}")

    record["documents"] = documents
    artifact["failures"] = failures
    if not any(document["role"] == "main" for document in documents):
        artifact["status"] = "fail"
    elif failures:
        artifact["status"] = "fail"
    else:
        artifact["status"] = "pass"
    validate_paper_record_artifact(artifact)
    return artifact


def main() -> None:
    args = parser().parse_args()
    run_id = args.run_id or utc_run_id()
    if args.stage == "resolve":
        artifact = resolve_stage(
            args.input,
            run_id=run_id,
            paper_id=args.paper_id,
            offline=args.offline,
        )
    elif args.stage == "explicit":
        artifact = create_explicit_record(
            load_json_object(args.input),
            run_id=run_id,
            paper_id=args.paper_id,
            vault_root=args.vault_root,
            supplements=args.supplement,
        )
    else:
        artifact = load_json_object(args.input)
        validate_paper_record_artifact(artifact)
        if args.run_id and artifact["run_id"] != args.run_id:
            raise SystemExit("run_id does not match the input paper_record artifact")
        if args.paper_id and artifact["paper_id"] != args.paper_id:
            raise SystemExit("paper_id does not match the input paper_record artifact")
        if args.stage == "metadata":
            artifact = metadata_stage(artifact, offline=args.offline)
        else:
            artifact = fetch_stage(
                artifact,
                supplements=args.supplement,
                dest_dir=args.dest_dir,
                vault_root=args.vault_root,
                offline=args.offline,
            )
    emit_json(artifact, args.output or None)
    if artifact["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

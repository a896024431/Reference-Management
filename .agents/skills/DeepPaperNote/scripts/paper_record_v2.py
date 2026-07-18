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
    fitz,
    http_get_bytes,
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
    command.add_argument("--stage", choices=("resolve", "metadata", "fetch"), required=True)
    command.add_argument(
        "--input",
        required=True,
        help="Raw reference for resolve; v2 paper_record artifact otherwise.",
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
    command.add_argument("--offline", action="store_true", help="Skip network metadata enrichment.")
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


def resolve_stage(value: str, *, run_id: str, paper_id: str = "") -> dict[str, Any]:
    trusted = maybe_load_json_record(value)
    seed = dict(trusted) if trusted is not None else resolve_reference(value)
    payload = new_paper_record(seed, run_id=run_id, paper_id=paper_id)
    resolution_status = str(seed.get("status", "ok"))
    title = str(payload["paper_record"]["metadata"].get("title", "")).strip()
    if resolution_status in {"ambiguous", "unresolved"}:
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
    enriched = metadata if offline else enrich_metadata(metadata)
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


def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def _download(url: str, dest_dir: Path, *, fallback_name: str) -> Path:
    parsed_name = Path(urlparse(url).path).name
    name = parsed_name if parsed_name.lower().endswith(".pdf") else fallback_name
    target = dest_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(http_get_bytes(url))
    return target


def _main_source(metadata: dict[str, Any]) -> tuple[str, str]:
    local = str(metadata.get("local_pdf_path", "")).strip()
    if local and Path(local).expanduser().exists():
        return "local", local
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


def fetch_stage(
    artifact: dict[str, Any],
    *,
    supplements: list[str],
    dest_dir: str = "",
    vault_root: str = "",
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

    source_kind, source_value = _main_source(metadata)
    if not source_kind:
        failures.append("main_pdf_source_missing")
    else:
        try:
            fallback = f"{slugify_filename(str(metadata.get('title') or artifact['paper_id']))}.pdf"
            main_path, source, url = _materialize_source(
                source_value,
                dest_dir=target_dir,
                role="main",
                fallback_name=fallback,
            )
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
        artifact = resolve_stage(args.input, run_id=run_id, paper_id=args.paper_id)
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
            )
    emit_json(artifact, args.output or None)
    if artifact["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

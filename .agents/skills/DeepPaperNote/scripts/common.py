#!/usr/bin/env python3
"""Small local-only helpers shared by DeepPaperNote scripts.

DeepPaperNote starts from a PDF already mirrored into the Vault.  This module
therefore deliberately contains no URL parsing, provider lookup, download, or
metadata-enrichment entry point.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover - checked at the command boundary
    fitz = None


LOCAL_PDF_PREFIX_PATTERN = re.compile(r"^(?:[^-]{1,120})\s+-\s+(?:19|20)\d{2}\s+-\s+")
LOCAL_PDF_SUFFIX_ID_PATTERN = re.compile(r"\s*-\s*\d{4,}\s*$")
PDF_LIGATURE_MAP = {
    "\u00df": "ss",
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize_title(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", normalize_whitespace(text)).casefold()
    return normalize_whitespace(
        "".join(character if character.isalnum() else " " for character in normalized)
    )


def clean_local_pdf_stem(stem: str) -> str:
    """Remove common Zotero filename prefixes/suffixes without changing identity."""
    raw = normalize_whitespace((stem or "").replace("_", " "))
    if not raw:
        return ""
    cleaned = LOCAL_PDF_PREFIX_PATTERN.sub("", raw)
    cleaned = LOCAL_PDF_SUFFIX_ID_PATTERN.sub("", cleaned)
    return normalize_whitespace(cleaned) or raw


def normalize_pdf_text_artifacts(text: str) -> str:
    normalized = text or ""
    for original, replacement in PDF_LIGATURE_MAP.items():
        normalized = normalized.replace(original, replacement)
    return normalized


def extract_arxiv_id(text: str) -> str | None:
    value = (text or "").strip()
    for pattern in (
        r"arxiv:(\d{4}\.\d{4,5})(?:v\d+)?",
        r"abs/(\d{4}\.\d{4,5})(?:v\d+)?",
        r"pdf/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?",
        r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b",
    ):
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_doi(text: str) -> str | None:
    match = re.search(
        r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", text or "", flags=re.IGNORECASE
    )
    return match.group(1).rstrip(").,;") if match else None


def paper_id_for_record(record: dict[str, Any]) -> str:
    """Derive a stable local-record identity without any remote source field."""
    if record.get("paper_id"):
        return str(record["paper_id"])
    doi = extract_doi(str(record.get("doi", "")))
    if doi:
        return f"doi:{doi.casefold()}"
    arxiv_id = extract_arxiv_id(str(record.get("arxiv_id", "")))
    if arxiv_id:
        return f"arxiv:{arxiv_id.casefold()}"
    title = normalize_title(str(record.get("title", "")))
    seed = title or str(record.get("local_pdf_path", "")) or "unknown"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{'title' if title else 'paper'}:{digest}"


def split_sentences(text: str) -> list[str]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?。！？])\s+", normalized)
        if part.strip()
    ]


def clean_pdf_line(line: str) -> str:
    cleaned = normalize_whitespace(normalize_pdf_text_artifacts(line or ""))
    if not cleaned or re.fullmatch(r"(?:\d+|page \d+)", cleaned, flags=re.IGNORECASE):
        return ""
    return "" if len(cleaned) <= 2 else cleaned


def is_plausible_pdf_title_line(line: str) -> bool:
    normalized = clean_pdf_line(line)
    lower = normalized.lower()
    if len(normalized) < 20 or len(normalized.split()) < 4 or normalized.count(",") >= 3:
        return False
    forbidden = ("doi.org/", "http://", "https://", "www.", "check for updates")
    if any(token in lower for token in forbidden):
        return False
    if lower in {"abstract", "article", "preprint"}:
        return False
    if lower.startswith(("npj |", "arxiv:", "submitted to")) or " doi:" in lower:
        return False
    return not lower.startswith("doi:")


def first_page_title_candidate(first_page_text: str) -> str:
    for raw_line in (first_page_text or "").splitlines():
        if is_plausible_pdf_title_line(raw_line):
            return clean_pdf_line(raw_line)
    return ""


def extract_local_pdf_hints(pdf_path: Path) -> dict[str, Any]:
    """Read only local metadata/text; unreadable PDFs retain a filename fallback."""
    raw_title = normalize_whitespace(pdf_path.stem.replace("_", " "))
    hints: dict[str, Any] = {
        "title": clean_local_pdf_stem(pdf_path.stem) or raw_title,
        "title_source": "filename",
    }
    if fitz is None:
        return hints

    metadata_title = ""
    metadata_subject = ""
    first_page_text = ""
    try:
        document = fitz.open(pdf_path)
    except Exception:
        return hints
    try:
        metadata = document.metadata or {}
        metadata_title = normalize_whitespace(str(metadata.get("title", "")))
        metadata_subject = normalize_whitespace(str(metadata.get("subject", "")))
        if len(document):
            first_page_text = document[0].get_text("text")
    except Exception:
        return hints
    finally:
        document.close()

    if metadata_title:
        hints.update(title=metadata_title, title_source="metadata")
    elif title := first_page_title_candidate(first_page_text):
        hints.update(title=title, title_source="first_page")

    searchable = "\n".join(
        part for part in (metadata_subject, metadata_title, first_page_text) if part
    )
    if doi := extract_doi(searchable):
        hints["doi"] = doi
    if arxiv_id := extract_arxiv_id(searchable):
        hints["arxiv_id"] = arxiv_id
    return hints

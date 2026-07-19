#!/usr/bin/env python3
"""Shared helpers for DeepPaperNote scripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
DEFAULT_USER_AGENT = "DeepPaperNote/1"

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None


def ensure_parent(path: str | Path) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def emit(payload: dict[str, Any], output_path: str | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path:
        ensure_parent(output_path)
        Path(output_path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def load_json_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Expected a JSON object.")
    return data


def maybe_load_json_record(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    path = Path(stripped).expanduser()
    if path.exists() and path.is_file() and path.suffix.lower() == ".json":
        return load_json_file(path)
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    return None


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def strip_tags(text: str) -> str:
    return normalize_whitespace(re.sub(r"<[^>]+>", " ", text or ""))


def normalize_title(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", normalize_whitespace(text)).casefold()
    return normalize_whitespace(
        "".join(character if character.isalnum() else " " for character in normalized)
    )


LOCAL_PDF_PREFIX_PATTERN = re.compile(r"^(?:[^-]{1,120})\s+-\s+(?:19|20)\d{2}\s+-\s+")
LOCAL_PDF_SUFFIX_ID_PATTERN = re.compile(r"\s*-\s*\d{4,}\s*$")
PREPRINT_HINTS = (
    "medrxiv",
    "biorxiv",
    "preprint",
    "arxiv",
    "10.1101/",
    "10.21203/rs.",
    "preprints.org",
)
PDF_LIGATURE_MAP = {
    "\u00df": "ss",
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}


def clean_local_pdf_stem(stem: str) -> str:
    raw = normalize_whitespace((stem or "").replace("_", " "))
    if not raw:
        return ""
    cleaned = LOCAL_PDF_PREFIX_PATTERN.sub("", raw)
    cleaned = LOCAL_PDF_SUFFIX_ID_PATTERN.sub("", cleaned)
    cleaned = normalize_whitespace(cleaned)
    return cleaned or raw


def is_probable_local_pdf_artifact_title(title: str) -> bool:
    normalized = normalize_whitespace(title)
    if not normalized:
        return False
    if LOCAL_PDF_PREFIX_PATTERN.match(normalized):
        return True
    if LOCAL_PDF_SUFFIX_ID_PATTERN.search(normalized):
        return True
    return bool(
        re.search(r"\b(?:et al\.?|等)\b", normalized, flags=re.IGNORECASE)
        and re.search(r"\b(?:19|20)\d{2}\b", normalized)
    )


def normalize_pdf_text_artifacts(text: str) -> str:
    normalized = text or ""
    for original, replacement in PDF_LIGATURE_MAP.items():
        normalized = normalized.replace(original, replacement)
    return normalized


def slugify_filename(text: str) -> str:
    text = normalize_whitespace(text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text).strip("_")
    return text or "paper_note"


def env_config_value(*names: str, default: str = "") -> str:
    """Read an optional integration value from the current process environment only."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def title_similarity(a: str, b: str) -> float:
    a_norm = normalize_title(a)
    b_norm = normalize_title(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    words_a = set(a_norm.split())
    words_b = set(b_norm.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def publication_quality_score(record: dict[str, Any]) -> int:
    venue = normalize_whitespace(str(record.get("venue", ""))).lower()
    source_url = normalize_whitespace(str(record.get("source_url", ""))).lower()
    source = normalize_whitespace(str(record.get("source", ""))).lower()
    doi = normalize_whitespace(str(record.get("doi", ""))).lower()
    joined = " ".join([venue, source_url, source, doi])
    if any(token in joined for token in PREPRINT_HINTS):
        return 0
    if venue or source == "crossref":
        return 2
    return 1


def candidate_priority_score(record: dict[str, Any]) -> int:
    source = normalize_whitespace(str(record.get("source", ""))).lower()
    source_url = normalize_whitespace(str(record.get("source_url", ""))).lower()
    doi = normalize_whitespace(str(record.get("doi", ""))).lower()
    joined = " ".join([source, source_url, doi])

    if "10.20944/preprints" in joined or any(token in joined for token in PREPRINT_HINTS):
        return 0

    if record.get("doi") and publication_quality_score(record) >= 2:
        return 4

    if record.get("arxiv_id") or source == "arxiv" or "arxiv.org" in source_url:
        return 3

    if record.get("pdf_url"):
        return 2

    return 1


def extract_arxiv_id(paper_ref: str) -> str | None:
    paper_ref = (paper_ref or "").strip()
    patterns = [
        r"arxiv:(\d{4}\.\d{4,5})(?:v\d+)?",
        r"abs/(\d{4}\.\d{4,5})(?:v\d+)?",
        r"pdf/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?",
        r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, paper_ref, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_doi(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).rstrip(").,;]")


def is_probable_url(text: str) -> bool:
    return bool(re.match(r"^https?://", (text or "").strip(), flags=re.IGNORECASE))


def is_probable_zotero_key(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{8}", (text or "").strip()))


def infer_source_type(value: str) -> str:
    stripped = (value or "").strip()
    if not stripped:
        return "unknown"
    path = Path(stripped).expanduser()
    if path.exists() and path.is_file() and path.suffix.lower() == ".pdf":
        return "local_pdf"
    if is_probable_url(stripped):
        if extract_arxiv_id(stripped):
            return "arxiv_url"
        if urllib.parse.urlparse(stripped).path.lower().endswith(".pdf"):
            return "pdf_url"
        if extract_doi(stripped):
            return "doi_url"
        return "url"
    if extract_arxiv_id(stripped):
        return "arxiv_id"
    if extract_doi(stripped):
        return "doi"
    if is_probable_zotero_key(stripped):
        return "zotero_key"
    return "title"


def paper_id_for_record(record: dict[str, Any]) -> str:
    if record.get("paper_id"):
        return str(record["paper_id"])
    doi = extract_doi(str(record.get("doi", "")))
    if doi:
        return f"doi:{doi.casefold()}"
    arxiv_id = extract_arxiv_id(str(record.get("arxiv_id", "")))
    if arxiv_id:
        return f"arxiv:{arxiv_id.casefold()}"
    if record.get("zotero_key"):
        return f"zotero:{record['zotero_key']}"
    if record.get("title"):
        digest = hashlib.sha1(normalize_title(str(record["title"])).encode("utf-8")).hexdigest()[
            :12
        ]
        return f"title:{digest}"
    source = str(record.get("source_url") or record.get("local_pdf_path") or "unknown")
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    return f"paper:{digest}"


def http_get_text(url: str, *, timeout: int = 30, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def http_get_json(
    url: str, *, timeout: int = 30, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    return json.loads(http_get_text(url, timeout=timeout, headers=headers))


def http_get_bytes(url: str, *, timeout: int = 60, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def semantic_scholar_headers() -> dict[str, str]:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    api_key = env_config_value("DEEPPAPERNOTE_SEMANTIC_SCHOLAR_API_KEY", "SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def parse_arxiv_xml(xml_content: str) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    root = ET.fromstring(xml_content)
    for entry in root.findall("atom:entry", ARXIV_NS):
        paper: dict[str, Any] = {
            "source": "arxiv",
            "source_type": "arxiv",
            "metadata_sources": ["arxiv"],
        }
        id_elem = entry.find("atom:id", ARXIV_NS)
        if id_elem is not None and id_elem.text:
            paper["source_url"] = normalize_whitespace(id_elem.text)
            paper["url"] = paper["source_url"]
            arxiv_id = extract_arxiv_id(paper["source_url"])
            if arxiv_id:
                paper["arxiv_id"] = arxiv_id

        title_elem = entry.find("atom:title", ARXIV_NS)
        paper["title"] = normalize_whitespace(title_elem.text if title_elem is not None else "")

        summary_elem = entry.find("atom:summary", ARXIV_NS)
        paper["abstract"] = normalize_whitespace(
            summary_elem.text if summary_elem is not None else ""
        )

        journal_ref_elem = entry.find("arxiv:journal_ref", ARXIV_NS)
        journal_ref = normalize_whitespace(
            journal_ref_elem.text if journal_ref_elem is not None else ""
        )
        if journal_ref:
            paper["venue"] = journal_ref

        doi_elem = entry.find("arxiv:doi", ARXIV_NS)
        if doi_elem is not None and doi_elem.text:
            paper["doi"] = normalize_whitespace(doi_elem.text)

        authors = []
        for author in entry.findall("atom:author", ARXIV_NS):
            name_elem = author.find("atom:name", ARXIV_NS)
            if name_elem is not None and name_elem.text:
                authors.append(normalize_whitespace(name_elem.text))
        paper["authors"] = authors

        published_elem = entry.find("atom:published", ARXIV_NS)
        if published_elem is not None and published_elem.text:
            paper["published"] = normalize_whitespace(published_elem.text)
            if re.match(r"^\d{4}", paper["published"]):
                paper["year"] = paper["published"][:4]

        for link in entry.findall("atom:link", ARXIV_NS):
            if link.get("title") == "pdf" and link.get("href"):
                paper["pdf_url"] = str(link.get("href"))
                break

        papers.append(paper)
    return papers


def fetch_arxiv_entries(
    *, search_query: str = "", id_list: str = "", max_results: int = 10
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "id_list": id_list,
            "start": 0,
            "max_results": max_results,
        }
    )
    try:
        xml_content = http_get_text(f"https://export.arxiv.org/api/query?{params}")
    except Exception:
        return []
    if not normalize_whitespace(xml_content):
        return []
    try:
        return parse_arxiv_xml(xml_content)
    except Exception:
        return []


def safe_fetch_arxiv_entries(
    *, search_query: str = "", id_list: str = "", max_results: int = 10
) -> list[dict[str, Any]]:
    try:
        return fetch_arxiv_entries(
            search_query=search_query, id_list=id_list, max_results=max_results
        )
    except Exception:
        return []


def normalize_crossref_work(item: dict[str, Any]) -> dict[str, Any]:
    title = normalize_whitespace(" ".join(item.get("title") or []))
    authors = []
    affiliations = []
    for author in item.get("author", []) or []:
        given = normalize_whitespace(str(author.get("given", "")))
        family = normalize_whitespace(str(author.get("family", "")))
        name = normalize_whitespace(" ".join(part for part in [given, family] if part))
        if name:
            authors.append(name)
        for aff in author.get("affiliation", []) or []:
            aff_name = normalize_whitespace(str(aff.get("name", "")))
            if aff_name and aff_name not in affiliations:
                affiliations.append(aff_name)
    venue = normalize_whitespace(" ".join(item.get("container-title") or []))
    published = (
        item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or item.get("issued", {}).get("date-parts")
        or []
    )
    year = ""
    if (
        published
        and isinstance(published, list)
        and isinstance(published[0], list)
        and published[0]
    ):
        year = str(published[0][0])
    doi = normalize_whitespace(str(item.get("DOI", "")))
    source_url = normalize_whitespace(str(item.get("URL", "")))
    return {
        "title": title,
        "authors": authors,
        "affiliations": affiliations,
        "venue": venue,
        "doi": doi,
        "source": "crossref",
        "source_type": "crossref",
        "source_url": source_url,
        "year": year,
        "published": year,
        "abstract": strip_tags(str(item.get("abstract", ""))),
        "metadata_sources": ["crossref"],
    }


def fetch_crossref_by_doi(doi: str) -> dict[str, Any] | None:
    url = f"{CROSSREF_WORKS_URL}/{urllib.parse.quote(doi)}"
    try:
        data = http_get_json(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    except Exception:
        return None
    message = data.get("message") or {}
    if not isinstance(message, dict):
        return None
    return normalize_crossref_work(message)


def search_crossref_by_title(title: str, *, limit: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query.title": title, "rows": limit})
    try:
        data = http_get_json(
            f"{CROSSREF_WORKS_URL}?{params}", headers={"User-Agent": DEFAULT_USER_AGENT}
        )
    except Exception:
        return []
    items = data.get("message", {}).get("items", []) or []
    return [normalize_crossref_work(item) for item in items if isinstance(item, dict)]


def normalize_semantic_scholar_paper(paper: dict[str, Any]) -> dict[str, Any]:
    ext_ids = paper.get("externalIds") or {}
    doi = normalize_whitespace(str(ext_ids.get("DOI", "")))
    arxiv_id = normalize_whitespace(str(ext_ids.get("ArXiv", "")))
    affiliations: list[str] = []
    authors: list[str] = []
    for author in paper.get("authors", []) or []:
        if not isinstance(author, dict):
            continue
        name = normalize_whitespace(str(author.get("name", "")))
        if name:
            authors.append(name)
        raw_affs = author.get("affiliations", []) or []
        if isinstance(raw_affs, str):
            raw_affs = [raw_affs]
        for aff in raw_affs:
            aff_name = normalize_whitespace(str(aff))
            if aff_name and aff_name not in affiliations:
                affiliations.append(aff_name)
    result = {
        "title": normalize_whitespace(str(paper.get("title", ""))),
        "abstract": normalize_whitespace(str(paper.get("abstract", ""))),
        "authors": authors,
        "affiliations": affiliations,
        "venue": normalize_whitespace(str(paper.get("venue", ""))),
        "year": normalize_whitespace(str(paper.get("year", ""))),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "source": "semantic_scholar",
        "source_type": "semantic_scholar",
        "source_url": normalize_whitespace(str(paper.get("url", ""))),
        "metadata_sources": ["semantic_scholar"],
    }
    if arxiv_id and not result.get("pdf_url"):
        result["pdf_url"] = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return result


def search_semantic_scholar(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "limit": limit,
            "fields": "title,abstract,year,venue,url,externalIds,authors.name,authors.affiliations",
        }
    )
    try:
        data = http_get_json(
            f"{SEMANTIC_SCHOLAR_SEARCH_URL}?{params}",
            headers=semantic_scholar_headers(),
        )
    except Exception:
        return []
    items = data.get("data", []) or []
    return [normalize_semantic_scholar_paper(item) for item in items if isinstance(item, dict)]


def normalize_openalex_work(item: dict[str, Any]) -> dict[str, Any]:
    title = normalize_whitespace(str(item.get("display_name", "")))
    authors = []
    affiliations = []
    for authorship in item.get("authorships", []) or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author", {}) or {}
        name = normalize_whitespace(str(author.get("display_name", "")))
        if name:
            authors.append(name)
        for institution in authorship.get("institutions", []) or []:
            if not isinstance(institution, dict):
                continue
            inst_name = normalize_whitespace(str(institution.get("display_name", "")))
            if inst_name and inst_name not in affiliations:
                affiliations.append(inst_name)
    ids = item.get("ids", {}) or {}
    doi_url = normalize_whitespace(str(ids.get("doi", "")))
    doi = extract_doi(doi_url or normalize_whitespace(str(item.get("doi", "")))) or ""
    primary_location = item.get("primary_location", {}) or {}
    pdf_url = normalize_whitespace(str((primary_location.get("pdf_url") or "")))
    if not pdf_url:
        best_oa = item.get("best_oa_location", {}) or {}
        pdf_url = normalize_whitespace(str(best_oa.get("pdf_url") or ""))
    venue = normalize_whitespace(
        str((primary_location.get("source", {}) or {}).get("display_name", ""))
    )
    year = normalize_whitespace(str(item.get("publication_year", "")))
    return {
        "title": title,
        "authors": authors,
        "affiliations": affiliations,
        "venue": venue,
        "year": year,
        "doi": doi,
        "source": "openalex",
        "source_type": "openalex",
        "source_url": normalize_whitespace(str(item.get("id", ""))),
        "pdf_url": pdf_url,
        "abstract": "",
        "metadata_sources": ["openalex"],
    }


def fetch_openalex_by_doi(doi: str) -> dict[str, Any] | None:
    url = f"{OPENALEX_WORKS_URL}/https://doi.org/{urllib.parse.quote(doi, safe='')}"
    try:
        data = http_get_json(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return normalize_openalex_work(data)


def search_openalex_by_title(title: str, *, limit: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"search": title, "per-page": limit})
    try:
        data = http_get_json(
            f"{OPENALEX_WORKS_URL}?{params}", headers={"User-Agent": DEFAULT_USER_AGENT}
        )
    except Exception:
        return []
    items = data.get("results", []) or []
    return [normalize_openalex_work(item) for item in items if isinstance(item, dict)]


def merge_metadata_records(*records: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    metadata_sources: list[str] = []
    additive_list_fields = {"affiliations", "metadata_sources"}
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if value in ("", None, [], {}):
                continue
            if key == "authors":
                if not merged.get("authors"):
                    values = value if isinstance(value, list) else [value]
                    seen = set()
                    deduped = []
                    for item in values:
                        cleaned = normalize_whitespace(str(item))
                        marker = normalize_title(cleaned)
                        if cleaned and marker and marker not in seen:
                            deduped.append(cleaned)
                            seen.add(marker)
                    if deduped:
                        merged["authors"] = deduped
                continue
            if key in additive_list_fields:
                current = merged.setdefault(key, [])
                if not isinstance(current, list):
                    current = []
                    merged[key] = current
                values = value if isinstance(value, list) else [value]
                for item in values:
                    cleaned = normalize_whitespace(str(item))
                    if cleaned and cleaned not in current:
                        current.append(cleaned)
                continue
            if key not in merged or merged[key] in ("", None):
                merged[key] = value
    for record in records:
        if isinstance(record, dict):
            for source in record.get("metadata_sources", []) or []:
                source_name = normalize_whitespace(str(source))
                if source_name and source_name not in metadata_sources:
                    metadata_sources.append(source_name)
    if metadata_sources:
        merged["metadata_sources"] = metadata_sources
    merged["paper_id"] = paper_id_for_record(merged)
    return merged


TITLE_MATCH_MIN_SIMILARITY = 0.80


def candidate_identity_keys(record: dict[str, Any]) -> set[str]:
    """Return stable identifiers that can join the same work across providers."""
    keys: set[str] = set()
    doi = extract_doi(str(record.get("doi", "")))
    if doi:
        keys.add(f"doi:{doi.casefold()}")
    arxiv_id = extract_arxiv_id(str(record.get("arxiv_id", "")))
    if arxiv_id:
        keys.add(f"arxiv:{arxiv_id.casefold()}")
    title = normalize_title(str(record.get("title", "")))
    year = normalize_whitespace(str(record.get("year") or record.get("published") or ""))[:4]
    if title and re.fullmatch(r"(?:19|20)\d{2}", year):
        keys.add(f"title-year:{title}:{year}")
    return keys


def _strong_identity_conflict(left: set[str], right: set[str]) -> bool:
    """Return true when two records carry incompatible DOI or arXiv identifiers."""
    for prefix in ("doi:", "arxiv:"):
        left_values = {key for key in left if key.startswith(prefix)}
        right_values = {key for key in right if key.startswith(prefix)}
        if left_values and right_values and left_values.isdisjoint(right_values):
            return True
    return False


def deduplicate_title_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge provider records that share a DOI, arXiv id, or normalized title/year."""
    groups: list[tuple[set[str], list[dict[str, Any]]]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        keys = candidate_identity_keys(candidate)
        matching = [
            index
            for index, (known, _) in enumerate(groups)
            if keys and known & keys and not _strong_identity_conflict(known, keys)
        ]
        if not matching:
            groups.append((set(keys), [candidate]))
            continue
        first = matching[0]
        groups[first][0].update(keys)
        groups[first][1].append(candidate)
        for index in reversed(matching[1:]):
            groups[first][0].update(groups[index][0])
            groups[first][1].extend(groups[index][1])
            groups.pop(index)

    merged: list[dict[str, Any]] = []
    for _, records in groups:
        ranked = sorted(
            records,
            key=lambda item: (
                candidate_priority_score(item),
                publication_quality_score(item),
                1 if item.get("doi") else 0,
                1 if item.get("arxiv_id") else 0,
                1 if item.get("abstract") else 0,
            ),
            reverse=True,
        )
        merged.append(merge_metadata_records(*ranked))
    return merged


def title_resolution(title: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve a title only when all credible provider hits describe one work."""
    credible = [
        item
        for item in candidates
        if title_similarity(title, str(item.get("title", ""))) >= TITLE_MATCH_MIN_SIMILARITY
    ]
    distinct = deduplicate_title_candidates(credible)
    if len(distinct) == 1:
        return {"status": "ok", "record": distinct[0], "candidates": []}

    summaries = []
    for item in sorted(
        distinct,
        key=lambda record: title_similarity(title, str(record.get("title", ""))),
        reverse=True,
    )[:5]:
        summaries.append(
            {
                "title": str(item.get("title", "")).strip(),
                "year": str(item.get("year") or item.get("published") or "").strip(),
                "doi": str(item.get("doi", "")).strip(),
                "arxiv_id": str(item.get("arxiv_id", "")).strip(),
                "source_url": str(item.get("source_url", "")).strip(),
                "similarity": round(title_similarity(title, str(item.get("title", ""))), 3),
            }
        )
    return {
        "status": "ambiguous" if len(distinct) > 1 else "unresolved",
        "record": None,
        "candidates": summaries,
    }


def choose_best_title_match(
    title: str,
    candidates: list[dict[str, Any]],
    *,
    minimum_similarity: float = TITLE_MATCH_MIN_SIMILARITY,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (
            title_similarity(title, str(item.get("title", ""))),
            candidate_priority_score(item),
            publication_quality_score(item),
            1 if item.get("doi") else 0,
            1 if item.get("pdf_url") else 0,
            1 if item.get("abstract") else 0,
        ),
        reverse=True,
    )
    best = ranked[0]
    if title_similarity(title, str(best.get("title", ""))) < minimum_similarity:
        return None
    return best


def resolve_reference(value: str) -> dict[str, Any]:
    source_type = infer_source_type(value)
    stripped = (value or "").strip()
    if source_type == "local_pdf":
        path = Path(stripped).expanduser().resolve()
        hints = extract_local_pdf_hints(path)
        paper = {
            "status": "ok",
            "source_type": "local_pdf",
            "source_url": str(path),
            "local_pdf_path": str(path),
            "title": normalize_whitespace(str(hints.get("title", "")))
            or clean_local_pdf_stem(path.stem)
            or path.stem.replace("_", " "),
            "metadata_sources": ["local_pdf"],
        }
        doi = normalize_whitespace(str(hints.get("doi", "")))
        arxiv_id = normalize_whitespace(str(hints.get("arxiv_id", "")))
        if doi:
            paper["doi"] = doi
        if arxiv_id:
            paper["arxiv_id"] = arxiv_id
        paper["paper_id"] = paper_id_for_record(paper)
        return paper
    if source_type == "arxiv_id":
        papers = safe_fetch_arxiv_entries(id_list=extract_arxiv_id(stripped) or "", max_results=1)
        if papers:
            paper = papers[0]
            paper["paper_id"] = paper_id_for_record(paper)
            paper["status"] = "ok"
            return paper
    if source_type == "arxiv_url":
        papers = safe_fetch_arxiv_entries(id_list=extract_arxiv_id(stripped) or "", max_results=1)
        if papers:
            paper = papers[0]
            paper["paper_id"] = paper_id_for_record(paper)
            paper["status"] = "ok"
            return paper
    if source_type in {"doi", "doi_url"}:
        doi = extract_doi(stripped) or ""
        paper = fetch_crossref_by_doi(doi) or {"doi": doi, "source_url": f"https://doi.org/{doi}"}
        paper["source_type"] = "doi"
        paper["source_url"] = paper.get("source_url") or f"https://doi.org/{doi}"
        paper["status"] = "ok"
        paper["paper_id"] = paper_id_for_record(paper)
        return paper
    if source_type == "pdf_url":
        filename = Path(urllib.parse.urlparse(stripped).path).stem or "paper"
        paper = {
            "status": "ok",
            "source_type": "pdf_url",
            "source_url": stripped,
            "pdf_url": stripped,
            "title": filename.replace("_", " "),
            "metadata_sources": ["pdf_url"],
        }
        paper["paper_id"] = paper_id_for_record(paper)
        return paper
    if source_type == "url":
        doi = extract_doi(stripped)
        if doi:
            return resolve_reference(doi)
        paper = {
            "status": "unsupported_url",
            "source_type": "url",
            "source_url": stripped,
            "metadata_sources": ["url"],
            "resolution_candidates": [],
        }
        paper["paper_id"] = paper_id_for_record(paper)
        return paper
    if source_type == "zotero_key":
        paper = {
            "status": "ok",
            "source_type": "zotero_key",
            "zotero_key": stripped,
            "source_url": "",
            "metadata_sources": ["zotero_key"],
        }
        paper["paper_id"] = paper_id_for_record(paper)
        return paper

    title = stripped
    candidates = (
        search_semantic_scholar(title, limit=5)
        + search_crossref_by_title(title, limit=5)
        + search_openalex_by_title(title, limit=5)
        + safe_fetch_arxiv_entries(search_query=f'ti:"{title}"', max_results=5)
    )
    resolution = title_resolution(title, candidates)
    best = resolution["record"]
    if isinstance(best, dict):
        best = merge_metadata_records(
            {
                "title": title,
                "source_type": "title_query",
                "source_url": "",
                "metadata_sources": ["title_query"],
            },
            best,
        )
        best["status"] = "ok"
        return best
    paper = {
        "status": resolution["status"],
        "source_type": "title_query",
        "title": title,
        "source_url": "",
        "metadata_sources": ["title_query"],
        "resolution_candidates": resolution["candidates"],
    }
    paper["paper_id"] = paper_id_for_record(paper)
    return paper


def enrich_metadata(record: dict[str, Any]) -> dict[str, Any]:
    base = dict(record)
    candidates: list[dict[str, Any]] = [base]
    doi = normalize_whitespace(str(base.get("doi", "")))
    title = normalize_whitespace(str(base.get("title", "")))
    arxiv_id = normalize_whitespace(str(base.get("arxiv_id", "")))

    if doi:
        crossref = fetch_crossref_by_doi(doi)
        if crossref:
            candidates.append(crossref)
        openalex = fetch_openalex_by_doi(doi)
        if openalex:
            candidates.append(openalex)
        sem = choose_best_title_match(title or doi, search_semantic_scholar(doi, limit=3))
        if sem:
            candidates.append(sem)

    if arxiv_id:
        arxiv = safe_fetch_arxiv_entries(id_list=arxiv_id, max_results=1)
        if arxiv:
            candidates.append(arxiv[0])

    if title:
        minimum_similarity = (
            0.55 if base.get("source_type") == "local_pdf" else TITLE_MATCH_MIN_SIMILARITY
        )
        sem = choose_best_title_match(
            title,
            search_semantic_scholar(title, limit=5),
            minimum_similarity=minimum_similarity,
        )
        if sem:
            candidates.append(sem)
        oa = choose_best_title_match(
            title,
            search_openalex_by_title(title, limit=5),
            minimum_similarity=minimum_similarity,
        )
        if oa:
            candidates.append(oa)
        cross = choose_best_title_match(
            title,
            search_crossref_by_title(title, limit=5),
            minimum_similarity=minimum_similarity,
        )
        if cross:
            candidates.append(cross)
        arxiv = choose_best_title_match(
            title,
            safe_fetch_arxiv_entries(search_query=f'ti:"{title}"', max_results=5),
            minimum_similarity=minimum_similarity,
        )
        if arxiv:
            candidates.append(arxiv)

    merged = merge_metadata_records(*candidates)
    if (
        not merged.get("year")
        and merged.get("published")
        and re.match(r"^\d{4}", str(merged["published"]))
    ):
        merged["year"] = str(merged["published"])[:4]
    if merged.get("doi") and not merged.get("source_url"):
        merged["source_url"] = f"https://doi.org/{merged['doi']}"
    if merged.get("arxiv_id") and not merged.get("pdf_url"):
        merged["pdf_url"] = f"https://arxiv.org/pdf/{merged['arxiv_id']}.pdf"
    if merged.get("arxiv_id") and not merged.get("doi"):
        merged["doi"] = f"10.48550/arXiv.{merged['arxiv_id']}"
    if base.get("source_type") == "local_pdf":
        corrected_title = choose_local_pdf_corrected_title(base, candidates[1:])
        if corrected_title:
            merged["title"] = corrected_title
    merged["paper_id"] = paper_id_for_record(merged)
    return merged


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def clean_pdf_line(line: str) -> str:
    line = re.sub(r"\s+", " ", normalize_pdf_text_artifacts(line or "")).strip()
    if not line:
        return ""
    if re.fullmatch(r"\d+", line):
        return ""
    if re.fullmatch(r"page \d+", line.lower()):
        return ""
    if len(line) <= 2:
        return ""
    return line


def is_plausible_pdf_title_line(line: str) -> bool:
    normalized = clean_pdf_line(line)
    lower = normalized.lower()
    if len(normalized) < 20 or len(normalized.split()) < 4:
        return False
    if normalized.count(",") >= 3:
        return False
    if any(
        token in lower for token in ["doi.org/", "http://", "https://", "www.", "check for updates"]
    ):
        return False
    if lower in {"abstract", "article", "preprint"}:
        return False
    if lower.startswith("npj |") or lower.startswith("arxiv:") or lower.startswith("submitted to"):
        return False
    if " doi:" in lower or lower.startswith("doi:"):
        return False
    return True


def first_page_title_candidate(first_page_text: str) -> str:
    for raw_line in (first_page_text or "").splitlines():
        if is_plausible_pdf_title_line(raw_line):
            return clean_pdf_line(raw_line)
    return ""


def extract_local_pdf_hints(pdf_path: Path) -> dict[str, Any]:
    raw_title = normalize_whitespace(pdf_path.stem.replace("_", " "))
    cleaned_title = clean_local_pdf_stem(pdf_path.stem)
    hints: dict[str, Any] = {
        "title": cleaned_title or raw_title,
        "title_source": "filename",
    }
    if fitz is None:
        return hints

    metadata_title = ""
    metadata_subject = ""
    first_page_text = ""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return hints
    try:
        metadata = doc.metadata or {}
        metadata_title = normalize_whitespace(str(metadata.get("title", "")))
        metadata_subject = normalize_whitespace(str(metadata.get("subject", "")))
        if len(doc):
            first_page_text = doc[0].get_text("text")
    except Exception:
        return hints
    finally:
        doc.close()

    if metadata_title:
        hints["title"] = metadata_title
        hints["title_source"] = "metadata"
    else:
        page_title = first_page_title_candidate(first_page_text)
        if page_title:
            hints["title"] = page_title
            hints["title_source"] = "first_page"

    searchable = "\n".join(
        part for part in [metadata_subject, metadata_title, first_page_text] if part
    )
    doi = extract_doi(searchable)
    if doi:
        hints["doi"] = doi
    arxiv_id = extract_arxiv_id(searchable)
    if arxiv_id:
        hints["arxiv_id"] = arxiv_id

    return hints


def choose_local_pdf_corrected_title(base: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    current_title = normalize_whitespace(str(base.get("title", "")))
    if not current_title or not is_probable_local_pdf_artifact_title(current_title):
        return ""
    titled_candidates = [
        candidate
        for candidate in candidates
        if normalize_whitespace(str(candidate.get("title", "")))
    ]
    if not titled_candidates:
        return ""
    best = max(
        titled_candidates,
        key=lambda item: (
            title_similarity(current_title, str(item.get("title", ""))),
            candidate_priority_score(item),
            publication_quality_score(item),
        ),
    )
    candidate_title = normalize_whitespace(str(best.get("title", "")))
    if not candidate_title:
        return ""
    if title_similarity(current_title, candidate_title) < 0.55:
        return ""
    if not (best.get("doi") or best.get("arxiv_id") or publication_quality_score(best) >= 2):
        return ""
    return candidate_title

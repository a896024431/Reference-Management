#!/usr/bin/env python3
"""Extract canonical, full-document schema-v2 evidence for one paper."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import clean_pdf_line, fitz, normalize_whitespace, split_sentences
from contracts_v2 import (
    PAPER_TYPES,
    PROFILE_REQUIREMENTS,
    artifact_header,
    emit_json,
    load_json_object,
    sha256_file,
    stable_id,
    validate_paper_record_artifact,
)

SECTION_ALIASES: dict[str, set[str]] = {
    "abstract": {"abstract", "summary"},
    "introduction": {
        "introduction",
        "background",
        "motivation",
        "preliminaries",
        "preliminary",
    },
    "method": {
        "method",
        "methods",
        "methodology",
        "approach",
        "experimental method",
        "experimental methods",
        "materials and methods",
        "device fabrication",
        "fabrication",
        "sample preparation",
        "experimental setup",
        "theoretical model",
        "model and methods",
    },
    "results": {
        "result",
        "results",
        "experiments",
        "experimental results",
        "results and discussion",
        "analysis",
        "evaluation",
        "observations",
    },
    "discussion": {"discussion", "general discussion"},
    "conclusion": {
        "conclusion",
        "conclusions",
        "summary and outlook",
        "outlook",
        "limitations",
        "future work",
    },
}
STOP_HEADINGS = {
    "references",
    "bibliography",
    "acknowledgments",
    "acknowledgements",
    "author contributions",
}


TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "problem": (
        "we address",
        "we investigate",
        "we study",
        "challenge",
        "open question",
        "remains unclear",
        "however",
        "aim",
        "goal",
    ),
    "protocol": (
        "we measure",
        "we fabricate",
        "we prepare",
        "we calculate",
        "we simulate",
        "method",
        "procedure",
        "device",
        "sample",
        "magnetic field",
        "temperature",
        "gate voltage",
        "training",
        "optimization",
    ),
    "results": (
        "we observe",
        "we find",
        "we demonstrate",
        "results show",
        "increases",
        "decreases",
        "scales",
        "consistent with",
        "outperform",
        "accuracy",
        "conductance",
        "resistance",
        "current",
        "visibility",
    ),
    "limitations": (
        "limitation",
        "future work",
        "remains",
        "cannot exclude",
        "not sufficient",
        "restricted to",
        "uncertainty",
        "further study",
    ),
    "data": (
        "dataset",
        "corpus",
        "participants",
        "patients",
        "samples",
        "measurements",
        "data were collected",
    ),
    "theory": (
        "hamiltonian",
        "field theory",
        "luttinger",
        "analytical",
        "theoretical model",
        "we derive",
        "calculation",
        "simulation",
    ),
    "fabrication": (
        "fabrication",
        "lithography",
        "anodic oxidation",
        "etching",
        "deposition",
        "anneal",
        "microscopy",
        "heterostructure",
    ),
}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True, help="Schema-v2 paper_record JSON.")
    command.add_argument("--output", default="")
    command.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Pages per document; 0 means all pages (the default).",
    )
    command.add_argument("--max-chars-per-chunk", type=int, default=900)
    return command


def infer_paper_type_v2(title: str, abstract: str = "") -> tuple[str, str]:
    lower = normalize_whitespace(f"{title} {abstract}").lower()
    if any(token in lower for token in ("survey", "review article", "tutorial", "perspective")):
        return "survey", "survey/review terminology"
    if any(
        token in lower for token in ("clinical", "patient", "psychiatric", "psychology", "hospital")
    ):
        return "clinical", "clinical or patient-study terminology"
    if any(
        token in lower
        for token in ("benchmark", "leaderboard", "evaluation suite", "dataset", "corpus")
    ):
        return "benchmark", "benchmark or dataset terminology"
    if any(
        token in lower
        for token in (
            "nanopattern",
            "nanofabrication",
            "lithography",
            "anodic oxidation",
            "device fabrication",
            "etching",
        )
    ):
        return "materials_fabrication", "fabrication/process terminology"
    physics_tokens = (
        "quantum hall",
        "graphene",
        "quasiparticle",
        "conductance",
        "heterostructure",
        "point contact",
        "electron transport",
        "condensed matter",
        "magnetic field",
    )
    experimental_tokens = (
        "we measure",
        "we observe",
        "experiment",
        "device",
        "temperature",
        "gate voltage",
        "transport",
    )
    if any(token in lower for token in physics_tokens) and any(
        token in lower for token in experimental_tokens
    ):
        return "experimental_physics", "physics subject with measurement/device signals"
    theoretical_tokens = (
        "theoretical",
        "hamiltonian",
        "field theory",
        "analytical solution",
        "we derive",
        "luttinger liquid",
    )
    if any(token in lower for token in theoretical_tokens):
        return "theoretical_physics", "theory/model terminology"
    ai_tokens = (
        "neural network",
        "machine learning",
        "large language model",
        "transformer",
        "training objective",
        "deep learning",
    )
    if any(token in lower for token in ai_tokens):
        return "ai_method", "machine-learning method terminology"
    humanities_tokens = (
        "ethnograph",
        "historical analysis",
        "discourse analysis",
        "qualitative study",
        "archives",
    )
    if any(token in lower for token in humanities_tokens):
        return "humanities", "humanities/social-science terminology"
    return "generic", "no specialized profile reached a reliable threshold"

def infer_release_profile(
    metadata: dict[str, Any], units: list[dict[str, Any]]
) -> tuple[str, str]:
    """Classify from full-text evidence, preferring experimental proof over title heuristics."""
    title = str(metadata.get("title", ""))
    abstract = str(metadata.get("abstract", ""))
    evidence_text = " ".join(
        str(unit.get("text", "")) for unit in units if isinstance(unit, dict)
    )
    combined = f"{title} {abstract} {evidence_text}".lower()
    title_lower = title.lower()
    if any(
        token in title_lower
        for token in (
            "nanopattern",
            "nanofabrication",
            "lithography",
            "anodic oxidation",
            "device fabrication",
        )
    ):
        return "materials_fabrication", "title identifies a fabrication/process paper"

    physics_signals = (
        "quantum hall",
        "graphene",
        "quasiparticle",
        "conductance",
        "heterostructure",
        "point contact",
        "electron transport",
        "condensed matter",
        "luttinger",
    )
    experimental_signals = (
        "we measure",
        "we measured",
        "measurement",
        "experimentally",
        "we observe",
        "we observed",
        "conductance",
        "resistance",
        "temperature dependence",
        "bias voltage",
        "gate voltage",
        "device",
        "data show",
    )
    physics_score = sum(token in combined for token in physics_signals)
    experimental_score = sum(token in combined for token in experimental_signals)
    if physics_score >= 1 and experimental_score >= 2:
        return (
            "experimental_physics",
            f"full text contains {experimental_score} independent measurement/device signals; "
            "theoretical interpretation does not override the experimental evidence chain",
        )
    return infer_paper_type_v2(title, abstract)


def normalize_heading_v2(line: str) -> str:
    value = normalize_whitespace(line).lower()
    value = re.sub(r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\s.():-]+", "", value)
    value = re.sub(r"[^a-z\s&]", " ", value)
    value = value.replace("&", "and")
    return normalize_whitespace(value)


def match_heading_v2(line: str) -> str | None:
    normalized = normalize_heading_v2(line)
    if normalized in STOP_HEADINGS:
        return "stop"
    for section, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return section
    return None


def read_pages(path: Path, *, max_pages: int = 0) -> tuple[list[dict[str, Any]], int]:
    if fitz is None:
        raise RuntimeError("PyMuPDF/fitz is required for page-aware evidence extraction")
    document = fitz.open(path)
    pages: list[dict[str, Any]] = []
    total_pages = len(document)
    try:
        limit = total_pages if max_pages <= 0 else min(total_pages, max_pages)
        for index in range(limit):
            text = document[index].get_text("text")
            pages.append(
                {
                    "page": index + 1,
                    "text": text,
                    "text_chars": len(normalize_whitespace(text)),
                }
            )
    finally:
        document.close()
    return pages, total_pages


def segment_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    current = "preamble"
    reached_references = False
    for page in pages:
        page_fragments: dict[str, list[str]] = defaultdict(list)
        for raw_line in str(page["text"]).splitlines():
            line = clean_pdf_line(raw_line)
            if not line:
                continue
            heading = match_heading_v2(line)
            if heading == "stop":
                reached_references = True
                break
            if heading:
                current = heading
                continue
            page_fragments[current].append(line)
        for section, lines in page_fragments.items():
            text = normalize_whitespace(" ".join(lines))
            if text:
                fragments.append({"page": page["page"], "section": section, "text": text})
        if reached_references:
            break
    return fragments


def chunk_fragment(fragment: dict[str, Any], *, max_chars: int) -> list[dict[str, Any]]:
    sentences = split_sentences(str(fragment["text"]))
    if not sentences:
        sentences = [str(fragment["text"])]
    chunks: list[dict[str, Any]] = []
    buffer = ""
    for sentence in sentences:
        candidate = normalize_whitespace(f"{buffer} {sentence}")
        if buffer and len(candidate) > max_chars:
            chunks.append({**fragment, "text": buffer})
            buffer = normalize_whitespace(sentence)
        else:
            buffer = candidate
    if buffer:
        chunks.append({**fragment, "text": buffer})
    return chunks


def evidence_types(text: str, section: str) -> list[str]:
    lower = text.lower()
    kinds = [
        kind for kind, keywords in TYPE_KEYWORDS.items() if any(word in lower for word in keywords)
    ]
    if section == "introduction" and "problem" not in kinds:
        kinds.append("problem")
    if section == "method" and "protocol" not in kinds:
        kinds.append("protocol")
    if section == "results" and "results" not in kinds:
        kinds.append("results")
    if section == "discussion" and any(word in lower for word in TYPE_KEYWORDS["limitations"]):
        kinds.append("limitations")
    if section == "conclusion" and "limitations" not in kinds:
        kinds.append("limitations")
    if re.search(r"\d", text) and any(
        token in lower
        for token in ("%", " hz", " k", " t", " v", " nm", "μm", "mev", "accuracy", "conductance")
    ):
        kinds.append("numeric")
    return sorted(set(kinds)) or ["general"]


def extract_references(text: str) -> dict[str, list[str]]:
    figures = re.findall(
        r"\b(?:Fig(?:ure)?\.?\s*(?:S?\d+[A-Za-z]?|[A-Z]\d+)|Extended Data Fig(?:ure)?\.?\s*\d+)\b",
        text,
        flags=re.IGNORECASE,
    )
    tables = re.findall(r"\bTable\.?\s*(?:S?\d+[A-Za-z]?|[A-Z]\d+)\b", text, flags=re.IGNORECASE)
    equations = re.findall(
        r"\bEq(?:uation)?\.?\s*\(?[A-Za-z]?\d+[A-Za-z]?\)?", text, flags=re.IGNORECASE
    )
    return {
        "figure_refs": list(dict.fromkeys(figures)),
        "table_refs": list(dict.fromkeys(tables)),
        "equation_refs": list(dict.fromkeys(equations)),
    }


CAPTION_RE = re.compile(
    r"^\s*((?:Fig(?:ure)?\.?\s*(?:S?\d+[A-Za-z]?|[A-Z]\d+)|"
    r"Extended Data Fig(?:ure)?\.?\s*\d+|Table\.?\s*(?:S?\d+[A-Za-z]?|[A-Z]\d+)))"
    r"\s*(?:[.:|—-])\s*(.{8,})$",
    flags=re.IGNORECASE,
)


def page_captions(page_text: str, *, page: int, document: dict[str, Any]) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line in page_text.splitlines():
        line = clean_pdf_line(raw_line)
        match = CAPTION_RE.match(line)
        if not match:
            continue
        label = normalize_whitespace(match.group(1))
        caption = normalize_whitespace(match.group(2))
        marker = f"{label.casefold()}::{caption.casefold()}"
        if marker in seen:
            continue
        seen.add(marker)
        captions.append(
            {
                "id": label,
                "caption": caption,
                "document_id": document["document_id"],
                "document_role": document["role"],
                "page": page,
                "page_hint": f"{document['role']} p. {page}",
            }
        )
    return captions


def build_evidence_artifact(
    paper_record_artifact: dict[str, Any],
    *,
    max_pages: int = 0,
    max_chars_per_chunk: int = 900,
) -> dict[str, Any]:
    validate_paper_record_artifact(paper_record_artifact)
    if max_pages < 0:
        raise ValueError("max_pages must be non-negative")
    paper_id = paper_record_artifact["paper_id"]
    run_id = paper_record_artifact["run_id"]
    record = paper_record_artifact["paper_record"]
    metadata = record["metadata"]
    paper_type, rationale = infer_paper_type_v2(
        str(metadata.get("title", "")),
        str(metadata.get("abstract", "")),
    )
    if paper_type not in PAPER_TYPES:
        paper_type = "generic"

    failures: list[str] = []
    page_records: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []

    documents = record.get("documents", [])
    if not any(document.get("role") == "main" for document in documents):
        failures.append("main_document_missing")
    for document in documents:
        document_id = str(document.get("document_id", ""))
        path = Path(str(document.get("path", ""))).expanduser()
        if not path.is_file():
            failures.append(f"document_missing:{document_id}")
            continue
        resolved_path = path.resolve()
        try:
            before_sha = sha256_file(resolved_path)
        except OSError as exc:
            failures.append(f"document_hash_failed:{document_id}:{exc}")
            continue
        expected_sha = str(document.get("sha256", ""))
        if before_sha != expected_sha:
            failures.append(
                f"document_sha256_mismatch:{document_id}:{expected_sha}/{before_sha}"
            )
            continue
        try:
            pages, total_pages = read_pages(resolved_path, max_pages=max_pages)
        except Exception as exc:
            failures.append(f"document_parse_failed:{document_id}:{exc}")
            continue
        try:
            after_sha = sha256_file(resolved_path)
        except OSError as exc:
            failures.append(f"document_hash_failed_after_extraction:{document_id}:{exc}")
            continue
        if after_sha != before_sha:
            failures.append(
                f"document_changed_during_extraction:{document_id}:{before_sha}/{after_sha}"
            )
            continue
        if int(document.get("pages", 0)) != total_pages:
            failures.append(
                f"document_page_count_changed:{document_id}:"
                f"{document.get('pages', 0)}/{total_pages}"
            )
        if max_pages > 0 and len(pages) < total_pages:
            failures.append(
                f"document_truncated:{document_id}:{len(pages)}/{total_pages}"
            )
        if not pages:
            failures.append(f"document_has_no_pages:{document_id}")
        else:
            text_page_count = sum(1 for page in pages if page["text_chars"] >= 80)
            if text_page_count / len(pages) < 0.6:
                failures.append(f"needs_ocr:{document_id}:text_coverage_below_60_percent")
        for page in pages:
            page_records.append(
                {
                    "document_id": document["document_id"],
                    "document_role": document["role"],
                    "page": page["page"],
                    "text_chars": page["text_chars"],
                }
            )
            captions.extend(page_captions(page["text"], page=page["page"], document=document))
        fragments = segment_pages(pages)
        for fragment in fragments:
            for chunk in chunk_fragment(fragment, max_chars=max_chars_per_chunk):
                refs = extract_references(chunk["text"])
                kinds = evidence_types(chunk["text"], chunk["section"])
                evidence_id = stable_id(
                    "ev",
                    document["document_id"],
                    chunk["page"],
                    chunk["section"],
                    chunk["text"],
                )
                unit = {
                    "evidence_id": evidence_id,
                    "document_id": document["document_id"],
                    "document_role": document["role"],
                    "page": chunk["page"],
                    "section": chunk["section"],
                    "types": kinds,
                    "text": chunk["text"],
                    **refs,
                }
                units.append(unit)

    available_types = {kind for unit in units for kind in unit["types"]}
    required_types = PROFILE_REQUIREMENTS[paper_type]
    missing_types = [kind for kind in required_types if kind not in available_types]
    text_pages = sum(1 for page in page_records if page["text_chars"] >= 80)
    needs_ocr = bool(page_records) and text_pages / len(page_records) < 0.6
    if not page_records:
        failures.append("no_pdf_pages_extracted")
    if missing_types:
        failures.append(f"missing_required_evidence:{','.join(missing_types)}")

    status = "fail" if failures else "pass"
    coverage = {
        "required": list(required_types),
        "available": sorted(available_types),
        "missing": missing_types,
        "ratio": round((len(required_types) - len(missing_types)) / max(len(required_types), 1), 3),
        "text_pages": text_pages,
        "total_pages": len(page_records),
        "needs_ocr": needs_ocr,
    }

    figures = [item for item in captions if str(item["id"]).lower().startswith(("fig", "extended"))]
    tables = [item for item in captions if str(item["id"]).lower().startswith("table")]
    pack = {
        "paper_id": paper_id,
        "paper_type": paper_type,
        "paper_type_rationale": rationale,
        "documents": documents,
        "coverage": coverage,
        "evidence_units": units,
        "page_records": page_records,
        "figure_captions": figures,
        "table_captions": tables,
        "evidence_quality": {"pass": "high", "fail": "low"}[status],
        "extraction_failures": failures,
    }
    artifact = artifact_header(
        "evidence_pack",
        paper_id=paper_id,
        run_id=run_id,
        status=status,
        failures=failures,
    )
    artifact["evidence_pack"] = pack
    artifact["summary"] = {
        "paper_type": paper_type,
        "paper_type_rationale": rationale,
        "coverage": coverage,
        "document_count": len(documents),
        "main_document_count": sum(1 for item in documents if item["role"] == "main"),
        "supplement_document_count": sum(1 for item in documents if item["role"] == "supplement"),
        "evidence_unit_count": len(units),
        "figure_caption_count": len(figures),
        "table_caption_count": len(tables),
    }
    return artifact



def build_contract_evidence(
    paper_record: dict[str, Any],
    *,
    max_pages: int = 0,
    max_chars_per_chunk: int = 900,
) -> dict[str, Any]:
    """Build the only supported evidence artifact and enforce the release profile contract."""
    artifact = build_evidence_artifact(
        paper_record,
        max_pages=max_pages,
        max_chars_per_chunk=max_chars_per_chunk,
    )
    pack = artifact["evidence_pack"]

    metadata = paper_record["paper_record"]["metadata"]
    paper_type, rationale = infer_release_profile(metadata, pack.get("evidence_units", []))
    pack["paper_type"] = paper_type
    pack["paper_type_rationale"] = rationale
    artifact["summary"]["paper_type"] = paper_type
    artifact["summary"]["paper_type_rationale"] = rationale

    available = set(pack.get("coverage", {}).get("available", []))
    required = PROFILE_REQUIREMENTS[paper_type]
    missing = [kind for kind in required if kind not in available]
    coverage = dict(pack.get("coverage", {}))
    coverage.update(
        {
            "required": list(required),
            "missing": missing,
            "ratio": round((len(required) - len(missing)) / max(len(required), 1), 3),
        }
    )
    pack["coverage"] = coverage
    artifact["summary"]["coverage"] = coverage
    failures = [
        item
        for item in artifact.get("failures", [])
        if not str(item).startswith("missing_required_evidence:")
    ]
    if missing:
        failures.append(f"missing_required_evidence:{','.join(missing)}")
    artifact["failures"] = failures
    pack["extraction_failures"] = failures
    artifact["status"] = "fail" if failures else "pass"
    pack["evidence_quality"] = {
        "pass": "high",
        "fail": "low",
    }[artifact["status"]]
    return artifact
def main() -> None:
    args = parser().parse_args()
    source = load_json_object(args.input)
    artifact = build_contract_evidence(
        source,
        max_pages=args.max_pages,
        max_chars_per_chunk=args.max_chars_per_chunk,
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

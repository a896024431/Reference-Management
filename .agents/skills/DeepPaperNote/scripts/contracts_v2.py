#!/usr/bin/env python3
"""Versioned contracts and validators for the DeepPaperNote v2 pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "2.0"
ARTIFACT_STATUSES = {"pass", "degraded", "fail"}
DOCUMENT_ROLES = {"main", "supplement"}
RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
WINDOWS_RESERVED_BASENAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
PAPER_TYPES = {
    "experimental_physics",
    "theoretical_physics",
    "materials_fabrication",
    "ai_method",
    "benchmark",
    "clinical",
    "humanities",
    "survey",
    "generic",
}
PROFILE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "experimental_physics": ("problem", "protocol", "results"),
    "theoretical_physics": ("problem", "theory", "results"),
    "materials_fabrication": ("problem", "fabrication", "results"),
    "ai_method": ("problem", "protocol", "results"),
    "benchmark": ("problem", "data", "results"),
    "clinical": ("problem", "data", "protocol", "results"),
    "humanities": ("problem", "protocol", "results"),
    "survey": ("problem", "results"),
    "generic": ("problem", "protocol", "results"),
}


class ContractError(ValueError):
    """Raised when a v2 artifact is missing required or consistent fields."""


def utc_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    return f"{prefix}-{stamp}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"Value is not canonical-JSON serializable: {exc}") from exc
    return sha256_text(rendered)


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


def validate_run_id(value: object) -> str:
    if not isinstance(value, str):
        raise ContractError("run_id must be a string")
    run_id = value
    windows_basename = run_id.split(".", 1)[0].casefold()
    if (
        run_id in {".", ".."}
        or len(run_id) > 128
        or run_id.endswith(".")
        or windows_basename in WINDOWS_RESERVED_BASENAMES
        or RUN_ID_RE.fullmatch(run_id) is None
    ):
        raise ContractError(
            "run_id must be a lowercase, non-reserved safe basename of at most 128 "
            "characters matching [a-z0-9][a-z0-9._-]*"
        )
    return run_id


def load_json_object(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    path = Path(value).expanduser()
    if path.exists() and path.is_file():
        data = json.loads(path.resolve().read_text(encoding="utf-8"))
    else:
        data = json.loads(str(value))
    if not isinstance(data, dict):
        raise ContractError("Expected a JSON object.")
    return data


def emit_json(payload: dict[str, Any], output: str | Path | None = None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output:
        target = Path(output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def artifact_header(
    artifact_type: str,
    *,
    paper_id: str,
    run_id: str,
    status: str = "pass",
    failures: Iterable[str] = (),
) -> dict[str, Any]:
    if not artifact_type.strip():
        raise ContractError("artifact_type must not be empty")
    if not paper_id.strip():
        raise ContractError("paper_id must not be empty")
    run_id = validate_run_id(run_id)
    if status not in ARTIFACT_STATUSES:
        raise ContractError(f"Invalid status: {status}")
    normalized_failures = [str(item) for item in failures if str(item).strip()]
    if status == "pass" and normalized_failures:
        raise ContractError("Passing artifacts must have an empty failures list")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "paper_id": paper_id,
        "run_id": run_id,
        "status": status,
        "failures": normalized_failures,
    }


def require_v2_artifact(
    artifact: dict[str, Any],
    *,
    artifact_type: str | Iterable[str] | None = None,
    allow_statuses: Iterable[str] = ARTIFACT_STATUSES,
) -> dict[str, Any]:
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(
            "Legacy or unknown artifact schema. Explicitly migrate it to schema_version 2.0."
        )
    actual_type = str(artifact.get("artifact_type", "")).strip()
    if not actual_type:
        raise ContractError("Missing artifact_type")
    if artifact_type is not None:
        expected = {artifact_type} if isinstance(artifact_type, str) else set(artifact_type)
        if actual_type not in expected:
            raise ContractError(f"Expected artifact_type {sorted(expected)}, got {actual_type!r}")
    if not str(artifact.get("paper_id", "")).strip():
        raise ContractError("Missing paper_id")
    validate_run_id(artifact.get("run_id", ""))
    status = str(artifact.get("status", ""))
    if status not in ARTIFACT_STATUSES:
        raise ContractError(f"Invalid artifact status: {status!r}")
    if status not in set(allow_statuses):
        raise ContractError(f"Artifact status {status!r} is not allowed here")
    failures = artifact.get("failures")
    if not isinstance(failures, list):
        raise ContractError("failures must be a list")
    if status == "pass" and failures:
        raise ContractError("Passing artifacts must have an empty failures list")
    return artifact


def require_same_identity(*artifacts: dict[str, Any]) -> tuple[str, str]:
    if not artifacts:
        raise ContractError("At least one artifact is required")
    for artifact in artifacts:
        require_v2_artifact(artifact)
    paper_ids = {str(item["paper_id"]) for item in artifacts}
    run_ids = {str(item["run_id"]) for item in artifacts}
    if len(paper_ids) != 1:
        raise ContractError(f"paper_id mismatch across artifacts: {sorted(paper_ids)}")
    if len(run_ids) != 1:
        raise ContractError(f"run_id mismatch across artifacts: {sorted(run_ids)}")
    return next(iter(paper_ids)), next(iter(run_ids))


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    required = ("document_id", "role", "sha256", "pages")
    missing = [key for key in required if key not in document]
    if missing:
        raise ContractError(f"Document missing fields: {', '.join(missing)}")
    if not str(document["document_id"]).strip():
        raise ContractError("Document document_id must not be empty")
    if document["role"] not in DOCUMENT_ROLES:
        raise ContractError(f"Invalid document role: {document['role']!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(document["sha256"])):
        raise ContractError("Document sha256 must be a 64-character lowercase hex digest")
    if not isinstance(document["pages"], int) or document["pages"] < 0:
        raise ContractError("Document pages must be a non-negative integer")
    if not (str(document.get("path", "")).strip() or str(document.get("url", "")).strip()):
        raise ContractError("Document must include path or url")
    return document


def validate_paper_record_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    require_v2_artifact(artifact, artifact_type="paper_record")
    record = artifact.get("paper_record")
    if not isinstance(record, dict):
        raise ContractError("paper_record artifact must contain paper_record object")
    if record.get("paper_id") != artifact.get("paper_id"):
        raise ContractError("paper_record.paper_id must match artifact paper_id")
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise ContractError("paper_record.metadata must be an object")
    if artifact["status"] != "fail" and not str(metadata.get("title", "")).strip():
        raise ContractError("paper_record.metadata.title is required for a usable record")
    documents = record.get("documents")
    if not isinstance(documents, list):
        raise ContractError("paper_record.documents must be a list")
    for document in documents:
        if not isinstance(document, dict):
            raise ContractError("Each document must be an object")
        validate_document(document)
    document_ids = [str(document["document_id"]) for document in documents]
    if len(document_ids) != len(set(document_ids)):
        raise ContractError("paper_record document_id values must be unique")
    main_count = sum(1 for document in documents if document.get("role") == "main")
    if main_count > 1:
        raise ContractError("paper_record may contain at most one main document")
    return artifact


def _string_list(value: Any, *, path: str, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{path} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractError(f"{path} must contain only non-empty strings")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{path} must not contain duplicates")
    if not allow_empty and not normalized:
        raise ContractError(f"{path} must not be empty")
    return normalized


def _evidence_units(value: Any, *, strict: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError("evidence_units must be a list")
    if not value:
        raise ContractError("evidence_units must not be empty")
    units: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    for index, unit in enumerate(value):
        path = f"evidence_units[{index}]"
        if not isinstance(unit, dict):
            raise ContractError(f"{path} must be an object")
        raw_evidence_id = unit.get("evidence_id")
        if not isinstance(raw_evidence_id, str) or not raw_evidence_id.strip():
            raise ContractError(f"{path}.evidence_id must not be empty")
        evidence_id = raw_evidence_id.strip()
        evidence_ids.append(evidence_id)
        if strict:
            if not isinstance(unit.get("document_id"), str) or not unit["document_id"].strip():
                raise ContractError(f"{path}.document_id must not be empty")
            if unit.get("document_role") not in DOCUMENT_ROLES:
                raise ContractError(f"{path}.document_role is invalid")
            page = unit.get("page")
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                raise ContractError(f"{path}.page must be a positive integer")
            if not isinstance(unit.get("section"), str) or not unit["section"].strip():
                raise ContractError(f"{path}.section must not be empty")
            _string_list(unit.get("types"), path=f"{path}.types", allow_empty=False)
            if not isinstance(unit.get("text"), str) or not unit["text"].strip():
                raise ContractError(f"{path}.text must not be empty")
            for refs_field in ("figure_refs", "table_refs", "equation_refs"):
                if refs_field in unit:
                    _string_list(unit[refs_field], path=f"{path}.{refs_field}")
        units.append(unit)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ContractError("evidence_id values must be unique")
    return units


def evidence_units_sha256(context_or_units: dict[str, Any] | list[Any]) -> str:
    units_value = (
        context_or_units.get("evidence_units")
        if isinstance(context_or_units, dict)
        else context_or_units
    )
    units = _evidence_units(units_value, strict=False)
    ordered = sorted(units, key=lambda item: str(item["evidence_id"]))
    return canonical_json_sha256(ordered)


def _document_index(documents: Any, *, path: str) -> dict[str, dict[str, Any]]:
    if not isinstance(documents, list) or not documents:
        raise ContractError(f"{path} must be a non-empty list")
    result: dict[str, dict[str, Any]] = {}
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            raise ContractError(f"{path}[{index}] must be an object")
        validate_document(document)
        document_id = str(document["document_id"])
        if document_id in result:
            raise ContractError(f"{path} contains duplicate document_id {document_id!r}")
        result[document_id] = document
    return result


def validate_evidence_pack_artifact(
    artifact: dict[str, Any],
    *,
    paper_record_artifact: dict[str, Any] | None = None,
    verify_files: bool = False,
) -> dict[str, Any]:
    require_v2_artifact(artifact, artifact_type="evidence_pack", allow_statuses={"pass"})
    pack = artifact.get("evidence_pack")
    if not isinstance(pack, dict):
        raise ContractError("evidence_pack object is required")
    if pack.get("paper_id") != artifact.get("paper_id"):
        raise ContractError("evidence_pack.paper_id must match artifact paper_id")
    if pack.get("paper_type") not in PAPER_TYPES:
        raise ContractError("evidence_pack.paper_type is invalid")
    if pack.get("evidence_quality") != "high":
        raise ContractError("Passing evidence_pack must have evidence_quality 'high'")

    pack_documents = _document_index(pack.get("documents"), path="evidence_pack.documents")
    main_count = sum(1 for item in pack_documents.values() if item["role"] == "main")
    if main_count != 1:
        raise ContractError("Passing evidence_pack must contain exactly one main document")
    for document_id, document in pack_documents.items():
        if document["pages"] < 1:
            raise ContractError(f"Document {document_id!r} must contain at least one page")

    source_documents = pack_documents
    if paper_record_artifact is not None:
        require_v2_artifact(
            paper_record_artifact,
            artifact_type="paper_record",
            allow_statuses={"pass"},
        )
        validate_paper_record_artifact(paper_record_artifact)
        require_same_identity(paper_record_artifact, artifact)
        source_documents = _document_index(
            paper_record_artifact["paper_record"].get("documents"),
            path="paper_record.documents",
        )
        if set(source_documents) != set(pack_documents):
            raise ContractError("evidence_pack documents do not match paper_record documents")
        for document_id, source in source_documents.items():
            packed = pack_documents[document_id]
            for field in ("role", "sha256", "pages"):
                if packed.get(field) != source.get(field):
                    raise ContractError(
                        f"evidence_pack document identity mismatch: {document_id}:{field}"
                    )

    if verify_files:
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover - environment gate covers this
            raise ContractError("PyMuPDF/fitz is required to verify evidence documents") from exc
        for document_id, document in source_documents.items():
            raw_path = str(document.get("path", "")).strip()
            if not raw_path:
                raise ContractError(
                    f"Document local PDF path is required for publication: {document_id}"
                )
            file_path = Path(raw_path).expanduser().resolve()
            if not file_path.is_file():
                raise ContractError(f"Document file is missing: {document_id}")
            if file_path.suffix.casefold() != ".pdf":
                raise ContractError(f"Document is not a PDF path: {document_id}")
            before_sha = sha256_file(file_path)
            if before_sha != document["sha256"]:
                raise ContractError(f"Document sha256 mismatch: {document_id}")
            try:
                pdf = fitz.open(file_path)
                try:
                    actual_pages = len(pdf)
                finally:
                    pdf.close()
            except Exception as exc:
                raise ContractError(f"Document PDF cannot be parsed: {document_id}: {exc}") from exc
            after_sha = sha256_file(file_path)
            if after_sha != before_sha or after_sha != document["sha256"]:
                raise ContractError(f"Document changed during verification: {document_id}")
            if actual_pages != document["pages"]:
                raise ContractError(
                    f"Document page count mismatch: {document_id}:"
                    f"expected={document['pages']}:actual={actual_pages}"
                )

    extraction_failures = pack.get("extraction_failures")
    if not isinstance(extraction_failures, list) or extraction_failures:
        raise ContractError("Passing evidence_pack must have empty extraction_failures")

    units = _evidence_units(pack.get("evidence_units"), strict=True)
    actual_types: set[str] = set()
    for index, unit in enumerate(units):
        document_id = str(unit["document_id"])
        document = pack_documents.get(document_id)
        if document is None:
            raise ContractError(f"evidence_units[{index}] refers to an unknown document")
        if unit["document_role"] != document["role"]:
            raise ContractError(f"evidence_units[{index}] document_role mismatch")
        if unit["page"] > document["pages"]:
            raise ContractError(f"evidence_units[{index}] page is outside the document")
        actual_types.update(str(item) for item in unit["types"])

    page_records = pack.get("page_records")
    if not isinstance(page_records, list):
        raise ContractError("evidence_pack.page_records must be a list")
    expected_pages = {
        (document_id, page)
        for document_id, document in pack_documents.items()
        for page in range(1, int(document["pages"]) + 1)
    }
    actual_pages: set[tuple[str, int]] = set()
    actual_text_pages = 0
    text_pages_by_document = {document_id: 0 for document_id in pack_documents}
    for index, page_record in enumerate(page_records):
        path = f"evidence_pack.page_records[{index}]"
        if not isinstance(page_record, dict):
            raise ContractError(f"{path} must be an object")
        document_id = str(page_record.get("document_id", ""))
        document = pack_documents.get(document_id)
        page = page_record.get("page")
        if document is None or not isinstance(page, int) or isinstance(page, bool):
            raise ContractError(f"{path} has an invalid document/page")
        if page_record.get("document_role") != document["role"]:
            raise ContractError(f"{path}.document_role mismatch")
        text_chars = page_record.get("text_chars")
        if not isinstance(text_chars, int) or isinstance(text_chars, bool) or text_chars < 0:
            raise ContractError(f"{path}.text_chars must be a non-negative integer")
        key = (document_id, page)
        if key in actual_pages:
            raise ContractError(f"Duplicate page record: {document_id} p. {page}")
        actual_pages.add(key)
        if text_chars >= 80:
            actual_text_pages += 1
            text_pages_by_document[document_id] += 1
    if actual_pages != expected_pages:
        raise ContractError("page_records do not cover every document page exactly once")

    coverage = pack.get("coverage")
    if not isinstance(coverage, dict):
        raise ContractError("evidence_pack.coverage must be an object")
    required = _string_list(
        coverage.get("required"), path="evidence_pack.coverage.required", allow_empty=False
    )
    expected_required = list(PROFILE_REQUIREMENTS[str(pack["paper_type"])])
    if required != expected_required:
        raise ContractError(
            "coverage.required does not match the requirements for evidence_pack.paper_type"
        )
    available = _string_list(
        coverage.get("available"), path="evidence_pack.coverage.available", allow_empty=False
    )
    missing = _string_list(coverage.get("missing"), path="evidence_pack.coverage.missing")
    if set(available) != actual_types:
        raise ContractError("coverage.available does not match evidence unit types")
    expected_missing = {item for item in required if item not in set(available)}
    if set(missing) != expected_missing:
        raise ContractError("coverage.missing is inconsistent with required/available")
    if missing:
        raise ContractError("Passing evidence_pack must not have missing coverage")
    ratio = coverage.get("ratio")
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or float(ratio) != 1.0:
        raise ContractError("Passing evidence_pack coverage ratio must be 1.0")
    if coverage.get("total_pages") != len(expected_pages):
        raise ContractError("coverage.total_pages does not match the document pages")
    if coverage.get("text_pages") != actual_text_pages:
        raise ContractError("coverage.text_pages does not match page_records")
    if coverage.get("needs_ocr") is not False:
        raise ContractError("Passing evidence_pack must not need OCR")
    if actual_text_pages / len(expected_pages) < 0.6:
        raise ContractError("Passing evidence_pack text coverage is below 60 percent")
    for document_id, document in pack_documents.items():
        if text_pages_by_document[document_id] / int(document["pages"]) < 0.6:
            raise ContractError(
                f"Passing evidence_pack text coverage is below 60 percent for {document_id}"
            )
    return artifact


NOTE_PLAN_FIELDS = (
    "paper_type",
    "dominant_domain",
    "evidence_ids",
    "must_cover",
    "key_claims",
    "key_numbers",
    "real_comparisons",
    "section_plan",
)
NOTE_PLAN_ENTRY_FIELDS = {
    "must_cover": "topic",
    "key_claims": "claim",
    "key_numbers": "number",
    "real_comparisons": "comparison",
    "section_plan": "section",
}
NOTE_PLAN_REQUIRED_LISTS = ("must_cover", "key_claims", "section_plan")


def _evidence_id_list(value: Any, *, path: str, allow_empty: bool) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{path} must be a list")
    normalized = [str(item).strip() for item in value]
    if any(not item for item in normalized):
        raise ContractError(f"{path} must contain only non-empty evidence IDs")
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{path} must not contain duplicate evidence IDs")
    if not allow_empty and not normalized:
        raise ContractError(f"{path} must not be empty")
    return normalized


def note_plan_bound_evidence_ids(plan: dict[str, Any]) -> set[str]:
    bound: set[str] = set()
    for field in NOTE_PLAN_ENTRY_FIELDS:
        entries = plan.get(field, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("evidence_ids"), list):
                bound.update(
                    str(item).strip() for item in entry["evidence_ids"] if str(item).strip()
                )
    return bound


def validate_note_plan_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    require_v2_artifact(artifact, artifact_type="note_plan", allow_statuses={"pass"})
    plan = artifact.get("note_plan")
    if not isinstance(plan, dict):
        raise ContractError("note_plan object is required")
    missing = [key for key in NOTE_PLAN_FIELDS if key not in plan]
    if missing:
        raise ContractError(f"note_plan missing fields: {', '.join(missing)}")
    unexpected = sorted(set(plan) - set(NOTE_PLAN_FIELDS))
    if unexpected:
        raise ContractError(f"note_plan has unexpected fields: {', '.join(unexpected)}")
    if plan["paper_type"] not in PAPER_TYPES:
        raise ContractError(f"Invalid paper_type: {plan['paper_type']!r}")
    if not str(plan["dominant_domain"]).strip():
        raise ContractError("note_plan.dominant_domain must not be empty")

    top_level_ids = set(
        _evidence_id_list(
            plan["evidence_ids"],
            path="note_plan.evidence_ids",
            allow_empty=False,
        )
    )
    for field, content_field in NOTE_PLAN_ENTRY_FIELDS.items():
        entries = plan[field]
        if not isinstance(entries, list):
            raise ContractError(f"note_plan.{field} must be a list")
        if field in NOTE_PLAN_REQUIRED_LISTS and not entries:
            raise ContractError(f"note_plan.{field} must not be empty")
        for index, entry in enumerate(entries):
            path = f"note_plan.{field}[{index}]"
            if not isinstance(entry, dict):
                raise ContractError(f"{path} must be an object")
            unexpected_entry_fields = sorted(set(entry) - {content_field, "evidence_ids"})
            if unexpected_entry_fields:
                raise ContractError(
                    f"{path} has unexpected fields: {', '.join(unexpected_entry_fields)}"
                )
            if not str(entry.get(content_field, "")).strip():
                raise ContractError(f"{path}.{content_field} must not be empty")
            _evidence_id_list(
                entry.get("evidence_ids"),
                path=f"{path}.evidence_ids",
                allow_empty=False,
            )

    bound_ids = note_plan_bound_evidence_ids(plan)
    if top_level_ids != bound_ids:
        missing_from_index = sorted(bound_ids - top_level_ids)
        unused_in_index = sorted(top_level_ids - bound_ids)
        details = []
        if missing_from_index:
            details.append("missing_from_evidence_ids=" + ",".join(missing_from_index))
        if unused_in_index:
            details.append("unused_evidence_ids=" + ",".join(unused_in_index))
        raise ContractError("note_plan evidence index mismatch: " + "; ".join(details))
    return artifact


SECOND_REVIEW_SCORE_FIELDS = (
    "factual_fidelity",
    "completeness",
    "domain_expression",
    "clarity",
    "chinese_naturalness",
    "navigability",
    "traceability",
)


REVIEW_ORIGINS = {"subagent", "human"}
MARKDOWN_HEADING_RE = re.compile(r"(?m)^(?:#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
MARKDOWN_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+")


def _normalized_heading(value: str) -> str:
    return " ".join(re.sub(r"^#{1,6}[ \t]+", "", value).strip().rstrip("#").split())


def _heading_sections(note_text: str) -> list[tuple[str, int, int]]:
    headings = list(MARKDOWN_HEADING_RE.finditer(note_text))
    return [
        (
            _normalized_heading(match.group(1)),
            match.end(),
            headings[index + 1].start() if index + 1 < len(headings) else len(note_text),
        )
        for index, match in enumerate(headings)
    ]


def _paragraph_spans(text: str, *, start: int, end: int) -> list[tuple[int, int]]:
    """Return Markdown paragraph/list-item spans within one heading section."""
    spans: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None
    position = start
    for line in text[start:end].splitlines(keepends=True):
        line_end = position + len(line)
        stripped = line.strip()
        is_list_item = bool(MARKDOWN_LIST_ITEM_RE.match(line))
        if not stripped:
            if current_start is not None and current_end is not None:
                spans.append((current_start, current_end))
            current_start = current_end = None
        elif is_list_item:
            if current_start is not None and current_end is not None:
                spans.append((current_start, current_end))
            current_start = position
            current_end = line_end
        else:
            if current_start is None:
                current_start = position
            current_end = line_end
        position = line_end
    if current_start is not None and current_end is not None:
        spans.append((current_start, current_end))
    return spans


def _reviewed_passage_span(
    note_text: str, *, heading: str, quote: str, path: str
) -> tuple[int, int]:
    expected_heading = _normalized_heading(heading)
    sections = [
        section for section in _heading_sections(note_text) if section[0] == expected_heading
    ]
    if not sections:
        raise ContractError(f"{path}.heading must name an actual Markdown heading")
    matches: list[tuple[int, int, int]] = []
    for _, section_start, section_end in sections:
        offset = note_text.find(quote, section_start, section_end)
        while offset >= 0:
            matches.append((offset, section_start, section_end))
            offset = note_text.find(quote, offset + len(quote), section_end)
    if len(matches) != 1:
        raise ContractError(
            f"{path}.quote must occur exactly once beneath its declared Markdown heading"
        )
    quote_start, section_start, section_end = matches[0]
    quote_end = quote_start + len(quote)
    for span_start, span_end in _paragraph_spans(
        note_text,
        start=section_start,
        end=section_end,
    ):
        if span_start <= quote_start and quote_end <= span_end:
            return span_start, span_end
    raise ContractError(f"{path}.quote must belong to a readable note paragraph")


def validate_second_review_artifact(
    artifact: dict[str, Any],
    *,
    context: dict[str, Any],
    note_text: str,
) -> dict[str, Any]:
    require_v2_artifact(artifact, artifact_type="second_review", allow_statuses={"pass"})
    review = artifact.get("review")
    if not isinstance(review, dict):
        raise ContractError("review object is required")
    require_v2_artifact(
        context,
        artifact_type="synthesis_bundle",
        allow_statuses={"pass"},
    )
    require_same_identity(artifact, context)
    known_evidence_ids = {
        str(unit["evidence_id"])
        for unit in _evidence_units(context.get("evidence_units"), strict=False)
    }
    expected_evidence_hash = evidence_units_sha256(context)
    actual_evidence_hash = str(artifact.get("evidence_units_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", actual_evidence_hash):
        raise ContractError("Review must contain a valid evidence_units_sha256")
    if actual_evidence_hash != expected_evidence_hash:
        raise ContractError("Review evidence_units_sha256 does not match synthesis context")
    expected_synthesis_hash = canonical_json_sha256(context)
    actual_synthesis_hash = str(artifact.get("synthesis_bundle_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", actual_synthesis_hash):
        raise ContractError("Review must contain a valid synthesis_bundle_sha256")
    if actual_synthesis_hash != expected_synthesis_hash:
        raise ContractError("Review synthesis_bundle_sha256 does not match synthesis context")

    author = str(artifact.get("author", "")).strip()
    reviewer = str(artifact.get("reviewer", "")).strip()
    origin = str(artifact.get("review_origin", "")).strip()
    if not author:
        raise ContractError("Passing review must identify its author")
    if not reviewer:
        raise ContractError("Passing review must identify its reviewer")
    if origin not in REVIEW_ORIGINS:
        raise ContractError(f"review_origin must be one of {sorted(REVIEW_ORIGINS)}")
    if author.casefold() == reviewer.casefold():
        raise ContractError("Review author and reviewer must be different")
    if str(review.get("author", "")).strip() != author:
        raise ContractError("review.author must match artifact author")
    if str(review.get("reviewer", "")).strip() != reviewer:
        raise ContractError("review.reviewer must match artifact reviewer")
    if str(review.get("review_origin", "")).strip() != origin:
        raise ContractError("review.review_origin must match artifact review_origin")

    scores = review.get("scores")
    if not isinstance(scores, dict):
        raise ContractError("review.scores must be an object")
    for field in SECOND_REVIEW_SCORE_FIELDS:
        value = scores.get(field)
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ContractError(f"review score {field} must be an integer from 1 to 5")
        if value < 4:
            raise ContractError(f"review score {field} must be at least 4 to pass")
    unresolved = review.get("unresolved_issues")
    if not isinstance(unresolved, list) or unresolved:
        raise ContractError("Passing review must have an empty unresolved_issues list")
    note_sha = str(artifact.get("note_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", note_sha):
        raise ContractError("Review must contain a valid note_sha256")
    if note_sha != sha256_text(note_text):
        raise ContractError("Second review does not match the current note text")
    checked = review.get("passages_checked")
    if not isinstance(checked, list) or len(checked) < 3:
        raise ContractError("Passing second review must check at least three note passages")
    normalized_quotes: list[str] = []
    passage_spans: list[tuple[int, int]] = []
    for index, passage in enumerate(checked):
        path = f"review.passages_checked[{index}]"
        if not isinstance(passage, dict):
            raise ContractError(f"{path} must be an object")
        heading = str(passage.get("heading", "")).strip()
        quote = str(passage.get("quote", "")).strip()
        if not heading or not quote:
            raise ContractError(f"{path} must contain heading and quote")
        passage_spans.append(
            _reviewed_passage_span(note_text, heading=heading, quote=quote, path=path)
        )
        normalized_quotes.append(" ".join(quote.split()).casefold())
        evidence_ids = _string_list(
            passage.get("evidence_ids"),
            path=f"{path}.evidence_ids",
            allow_empty=False,
        )
        unknown = sorted(set(evidence_ids) - known_evidence_ids)
        if unknown:
            raise ContractError(f"{path} contains unknown evidence IDs: {', '.join(unknown)}")
    if len(normalized_quotes) != len(set(normalized_quotes)):
        raise ContractError("Passing second review must check distinct note passages")
    if len(passage_spans) != len(set(passage_spans)):
        raise ContractError("Passing second review must check different note paragraphs")
    return artifact


def require_note_hash(note_text: str, *artifacts: dict[str, Any]) -> str:
    expected = sha256_text(note_text)
    for artifact in artifacts:
        actual = str(artifact.get("note_sha256", ""))
        if actual != expected:
            raise ContractError(
                f"Note hash mismatch for {artifact.get('artifact_type', 'artifact')}: "
                f"expected {expected}, got {actual or '<missing>'}"
            )
    return expected

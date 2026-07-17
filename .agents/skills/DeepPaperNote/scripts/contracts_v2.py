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


class ContractError(ValueError):
    """Raised when a v2 artifact is missing required or consistent fields."""


def utc_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


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
    if not run_id.strip():
        raise ContractError("run_id must not be empty")
    if status not in ARTIFACT_STATUSES:
        raise ContractError(f"Invalid status: {status}")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "paper_id": paper_id,
        "run_id": run_id,
        "status": status,
        "failures": [str(item) for item in failures if str(item).strip()],
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
    if not str(artifact.get("run_id", "")).strip():
        raise ContractError("Missing run_id")
    status = str(artifact.get("status", ""))
    if status not in ARTIFACT_STATUSES:
        raise ContractError(f"Invalid artifact status: {status!r}")
    if status not in set(allow_statuses):
        raise ContractError(f"Artifact status {status!r} is not allowed here")
    failures = artifact.get("failures")
    if not isinstance(failures, list):
        raise ContractError("failures must be a list")
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
    if not isinstance(metadata, dict) or not str(metadata.get("title", "")).strip():
        raise ContractError("paper_record.metadata.title is required")
    documents = record.get("documents")
    if not isinstance(documents, list):
        raise ContractError("paper_record.documents must be a list")
    for document in documents:
        if not isinstance(document, dict):
            raise ContractError("Each document must be an object")
        validate_document(document)
    main_count = sum(1 for document in documents if document.get("role") == "main")
    if main_count > 1:
        raise ContractError("paper_record may contain at most one main document")
    return artifact


def validate_note_plan_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    require_v2_artifact(artifact, artifact_type="note_plan", allow_statuses={"pass"})
    plan = artifact.get("note_plan")
    if not isinstance(plan, dict):
        raise ContractError("note_plan object is required")
    required = (
        "paper_type",
        "dominant_domain",
        "must_cover",
        "key_numbers",
        "real_comparisons",
        "section_plan",
    )
    missing = [key for key in required if key not in plan]
    if missing:
        raise ContractError(f"note_plan missing fields: {', '.join(missing)}")
    if plan["paper_type"] not in PAPER_TYPES:
        raise ContractError(f"Invalid paper_type: {plan['paper_type']!r}")
    for key in ("must_cover", "key_numbers", "real_comparisons", "section_plan"):
        if not isinstance(plan[key], list):
            raise ContractError(f"note_plan.{key} must be a list")
    if not plan["must_cover"] or not plan["section_plan"]:
        raise ContractError("note_plan must_cover and section_plan must not be empty")
    return artifact


QUALITY_SCORE_FIELDS = (
    "factual_fidelity",
    "completeness",
    "domain_expression",
    "clarity",
    "traceability",
)
READABILITY_SCORE_FIELDS = (
    "factual_fidelity",
    "completeness",
    "domain_expression",
    "chinese_naturalness",
    "navigability",
)


def validate_review_artifact(artifact: dict[str, Any], *, kind: str) -> dict[str, Any]:
    expected_type = f"{kind}_review"
    require_v2_artifact(artifact, artifact_type=expected_type, allow_statuses={"pass"})
    review = artifact.get("review")
    if not isinstance(review, dict):
        raise ContractError("review object is required")
    fields = QUALITY_SCORE_FIELDS if kind == "quality" else READABILITY_SCORE_FIELDS
    scores = review.get("scores")
    if not isinstance(scores, dict):
        raise ContractError("review.scores must be an object")
    for field in fields:
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

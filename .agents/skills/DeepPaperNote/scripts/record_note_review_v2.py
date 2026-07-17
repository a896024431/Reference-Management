#!/usr/bin/env python3
"""Bind an explicit model/human quality or readability review to one note hash."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from contracts_v2 import (
    QUALITY_SCORE_FIELDS,
    READABILITY_SCORE_FIELDS,
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    require_note_hash,
    require_same_identity,
    require_v2_artifact,
    sha256_text,
    validate_review_artifact,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--kind", required=True, choices=("quality", "readability"))
    command.add_argument("--input", required=True, help="Markdown note path.")
    command.add_argument("--review", required=True, help="Model/human review JSON.")
    command.add_argument("--context", required=True, help="Schema-v2 synthesis bundle.")
    command.add_argument(
        "--lint", default="", help="Passing lint report; required for readability."
    )
    command.add_argument("--output", default="")
    return command


def _validate_scores(scores: Any, fields: tuple[str, ...]) -> list[str]:
    failures: list[str] = []
    if not isinstance(scores, dict):
        return ["review_scores_missing"]
    for field in fields:
        value = scores.get(field)
        if not isinstance(value, int) or not 1 <= value <= 5:
            failures.append(f"review_score_invalid:{field}")
        elif value < 4:
            failures.append(f"review_score_below_four:{field}")
    return failures


def build_review_artifact(
    *,
    kind: str,
    note_text: str,
    review_source: dict[str, Any],
    context: dict[str, Any],
    lint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_v2_artifact(context, artifact_type="synthesis_bundle")
    if kind == "readability":
        if lint is None:
            raise ContractError("A passing lint report is required before readability review")
        require_v2_artifact(lint, artifact_type="lint_report", allow_statuses={"pass"})
        require_same_identity(context, lint)
        require_note_hash(note_text, lint)

    review = review_source.get("review", review_source)
    if not isinstance(review, dict):
        raise ContractError("review input must be a JSON object")
    normalized = dict(review)
    failures: list[str] = []
    if not str(normalized.get("reviewer", "")).strip():
        failures.append("reviewer_missing")
    if normalized.get("independent") is not True:
        failures.append("review_not_marked_independent")
    unresolved = normalized.get("unresolved_issues")
    if not isinstance(unresolved, list):
        failures.append("unresolved_issues_must_be_list")
    elif unresolved:
        failures.append("unresolved_review_issues_present")
    fields = QUALITY_SCORE_FIELDS if kind == "quality" else READABILITY_SCORE_FIELDS
    failures.extend(_validate_scores(normalized.get("scores"), fields))

    if kind == "quality":
        checked = normalized.get("claims_checked")
        if not isinstance(checked, list) or len(checked) < 3:
            failures.append("fewer_than_three_claims_checked")
        else:
            known_ids = {
                str(item.get("evidence_id", ""))
                for item in context.get("evidence_units", [])
                if isinstance(item, dict) and item.get("evidence_id")
            }
            for index, claim in enumerate(checked, start=1):
                if not isinstance(claim, dict):
                    failures.append(f"claim_check_not_object:{index}")
                    continue
                ids = claim.get("evidence_ids", [])
                if not isinstance(ids, list) or not ids:
                    failures.append(f"claim_check_missing_evidence:{index}")
                    continue
                unknown = [str(item) for item in ids if str(item) not in known_ids]
                if unknown:
                    failures.append(f"claim_check_unknown_evidence:{index}:{','.join(unknown)}")

    status = "pass" if not failures else "fail"
    artifact = artifact_header(
        f"{kind}_review",
        paper_id=str(context["paper_id"]),
        run_id=str(context["run_id"]),
        status=status,
        failures=failures,
    )
    artifact["note_sha256"] = sha256_text(note_text)
    artifact["review"] = normalized
    if lint is not None:
        artifact["lint_note_sha256"] = lint.get("note_sha256", "")
    if status == "pass":
        validate_review_artifact(artifact, kind=kind)
    return artifact


def main() -> None:
    args = parser().parse_args()
    note_text = Path(args.input).expanduser().resolve().read_text(encoding="utf-8")
    lint = load_json_object(args.lint) if args.lint else None
    artifact = build_review_artifact(
        kind=args.kind,
        note_text=note_text,
        review_source=load_json_object(args.review),
        context=load_json_object(args.context),
        lint=lint,
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

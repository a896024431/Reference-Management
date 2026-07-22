#!/usr/bin/env python3
"""Bind one substantive second-read review to a staged note and its evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from contracts_v2 import (
    SECOND_REVIEW_SCORE_FIELDS,
    ContractError,
    artifact_header,
    canonical_json_sha256,
    emit_json,
    evidence_units_sha256,
    load_json_object,
    require_v2_artifact,
    sha256_text,
    validate_second_review_artifact,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--author", required=True, help="Identity of the note author.")
    command.add_argument("--input", required=True, help="Staged Markdown note path.")
    command.add_argument("--review", required=True, help="Second-read review JSON.")
    command.add_argument("--context", required=True, help="Schema-v2 synthesis bundle.")
    command.add_argument("--output", default="")
    return command


def _validate_scores(scores: Any) -> list[str]:
    if not isinstance(scores, dict):
        return ["review_scores_missing"]
    failures: list[str] = []
    for field in SECOND_REVIEW_SCORE_FIELDS:
        value = scores.get(field)
        if not isinstance(value, int) or not 1 <= value <= 5:
            failures.append(f"review_score_invalid:{field}")
        elif value < 4:
            failures.append(f"review_score_below_threshold:{field}")
    return failures


def build_second_review_artifact(
    *,
    author: str,
    note_text: str,
    review_source: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    require_v2_artifact(context, artifact_type="synthesis_bundle", allow_statuses={"pass"})
    review = review_source.get("review", review_source)
    if not isinstance(review, dict):
        raise ContractError("review input must be a JSON object")
    normalized = dict(review)
    normalized_author = str(author).strip()
    reviewer = str(normalized.get("reviewer", "")).strip()
    origin = str(normalized.get("review_origin", "")).strip()
    normalized["author"] = normalized_author
    failures: list[str] = []
    if not normalized_author:
        failures.append("author_missing")
    if not reviewer:
        failures.append("reviewer_missing")
    if origin not in {"subagent", "human"}:
        failures.append("review_origin_invalid")
    if normalized_author and reviewer and normalized_author.casefold() == reviewer.casefold():
        failures.append("reviewer_matches_author")
    unresolved = normalized.get("unresolved_issues")
    if not isinstance(unresolved, list):
        failures.append("unresolved_issues_must_be_list")
    elif unresolved:
        failures.append("unresolved_review_issues_present")
    failures.extend(_validate_scores(normalized.get("scores")))

    passages = normalized.get("passages_checked")
    if not isinstance(passages, list) or len(passages) < 3:
        failures.append("fewer_than_three_passages_checked")

    artifact = artifact_header(
        "second_review",
        paper_id=str(context["paper_id"]),
        run_id=str(context["run_id"]),
        status="pass" if not failures else "fail",
        failures=failures,
    )
    artifact.update(
        {
            "note_sha256": sha256_text(note_text),
            "evidence_units_sha256": evidence_units_sha256(context),
            "synthesis_bundle_sha256": canonical_json_sha256(context),
            "author": normalized_author,
            "reviewer": reviewer,
            "review_origin": origin,
            "review": normalized,
        }
    )
    if artifact["status"] == "pass":
        validate_second_review_artifact(artifact, context=context, note_text=note_text)
    return artifact


def main() -> None:
    args = parser().parse_args()
    try:
        note_text = Path(args.input).expanduser().read_text(encoding="utf-8")
        artifact = build_second_review_artifact(
            author=args.author,
            note_text=note_text,
            review_source=load_json_object(args.review),
            context=load_json_object(args.context),
        )
    except (ContractError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    emit_json(artifact, args.output or None)
    if artifact["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

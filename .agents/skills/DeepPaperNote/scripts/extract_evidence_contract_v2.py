#!/usr/bin/env python3
"""Canonical evidence CLI with full-text-aware paper-profile classification."""

from __future__ import annotations

import argparse
from typing import Any

import extract_evidence_v2 as evidence_core
from contracts_v2 import emit_json, load_json_object, validate_paper_record_artifact


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True)
    command.add_argument("--output", default="")
    command.add_argument("--max-pages", type=int, default=0, help="0 means all pages.")
    command.add_argument("--max-chars-per-chunk", type=int, default=900)
    return command


def infer_release_profile(metadata: dict[str, Any], units: list[dict[str, Any]]) -> tuple[str, str]:
    title = str(metadata.get("title", ""))
    abstract = str(metadata.get("abstract", ""))
    evidence_text = " ".join(str(unit.get("text", "")) for unit in units if isinstance(unit, dict))
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

    return evidence_core.infer_paper_type_v2(title, abstract)


def build_contract_evidence(
    paper_record: dict[str, Any],
    *,
    max_pages: int = 0,
    max_chars_per_chunk: int = 900,
) -> dict[str, Any]:
    validate_paper_record_artifact(paper_record)
    artifact = evidence_core.build_evidence_artifact(
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
    required = evidence_core.PROFILE_REQUIREMENTS[paper_type]
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
    if not pack.get("page_records") or missing:
        artifact["status"] = "fail"
    elif failures:
        artifact["status"] = "degraded"
    else:
        artifact["status"] = "pass"
    pack["evidence_quality"] = {
        "pass": "high",
        "degraded": "medium",
        "fail": "low",
    }[artifact["status"]]
    return artifact


def main() -> None:
    args = parser().parse_args()
    artifact = build_contract_evidence(
        load_json_object(args.input),
        max_pages=args.max_pages,
        max_chars_per_chunk=args.max_chars_per_chunk,
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

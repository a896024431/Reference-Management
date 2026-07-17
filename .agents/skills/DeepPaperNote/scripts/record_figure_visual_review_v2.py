#!/usr/bin/env python3
"""Record a manifest-bound visual review for final inserted figure assets."""

from __future__ import annotations

import argparse

from contracts_v2 import emit_json, load_json_object
from figure_visual_review_contracts_v2 import build_figure_visual_review


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--manifest", required=True)
    command.add_argument("--decisions", required=True)
    command.add_argument("--contact-sheet-index", required=True)
    command.add_argument(
        "--review",
        required=True,
        help=(
            "JSON object with reviewer and reviews[]. Each inserted asset requires "
            "explicit complete, identity, and readable booleans."
        ),
    )
    command.add_argument("--output", required=True)
    return command


def main() -> None:
    args = parser().parse_args()
    artifact = build_figure_visual_review(
        manifest=load_json_object(args.manifest),
        decisions=load_json_object(args.decisions),
        contact_sheet=load_json_object(args.contact_sheet_index),
        review_source=load_json_object(args.review),
    )
    emit_json(artifact, args.output)
    if artifact["status"] != "pass":
        raise SystemExit("Figure visual review failed: " + "; ".join(artifact["failures"]))


if __name__ == "__main__":
    main()

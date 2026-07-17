#!/usr/bin/env python3
"""Render a DeepPaperNote v2 two-layer Markdown planning scaffold."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import maybe_load_json_record
from vault import render_note_scaffold


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "render note scaffold")
    p.add_argument("--input", required=True, help="Metadata JSON file or JSON object.")
    p.add_argument("--output", required=True, help="Output Markdown path.")
    return p


def main() -> None:
    args = parser().parse_args()
    record = maybe_load_json_record(args.input)
    if record is None:
        raise SystemExit("--input must be a metadata JSON file or JSON object")
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_note_scaffold(record), encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate a DeepPaperNote v2 Obsidian vault."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vault import lint_vault


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "lint DeepPaperNote vault")
    p.add_argument("--vault", default=".", help="Obsidian vault root (default: current directory).")
    p.add_argument("--output", default="", help="Optional JSON report path.")
    p.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit zero; useful for migration audits while preserving report status.",
    )
    return p


def main() -> None:
    args = parser().parse_args()
    report = lint_vault(Path(args.vault))
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    if report["status"] != "pass" and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

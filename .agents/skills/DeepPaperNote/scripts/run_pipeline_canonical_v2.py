#!/usr/bin/env python3
"""Final v2 runner using canonical evidence and figure contract entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import run_pipeline_release_v2 as release_runner

_run = release_runner.run


def canonical_run(command: list[str], *, stage: str, log: list[dict[str, Any]]) -> None:
    rewritten = [
        str(Path(item).with_name("extract_evidence_contract_v2.py"))
        if Path(item).name == "extract_evidence_v2.py"
        else item
        for item in command
    ]
    _run(rewritten, stage=stage, log=log)


def main() -> None:
    release_runner.run = canonical_run
    release_runner.main()


if __name__ == "__main__":
    main()

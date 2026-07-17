#!/usr/bin/env python3
"""Final single-paper v2 runner with canonical evidence and release figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import run_pipeline_release_v2 as release_runner

_run = release_runner.run


def final_run(command: list[str], *, stage: str, log: list[dict[str, Any]]) -> None:
    replacements = {
        "extract_evidence_v2.py": "extract_evidence_contract_v2.py",
        "plan_figures_contract_v2.py": "plan_figures_release_v2.py",
    }
    rewritten = [
        str(Path(item).with_name(replacements[Path(item).name]))
        if Path(item).name in replacements
        else item
        for item in command
    ]
    _run(rewritten, stage=stage, log=log)


def main() -> None:
    release_runner.run = final_run
    release_runner.main()


if __name__ == "__main__":
    main()

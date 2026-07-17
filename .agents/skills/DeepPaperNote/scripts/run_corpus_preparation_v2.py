#!/usr/bin/env python3
"""Prepare evidence, figures, and bundles for multiple existing v2 run directories."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

STAGES = ("evidence", "assets", "figures", "bundle")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--run-root", default=".local/deeppapernote/runs")
    command.add_argument("--run-id", action="append", required=True)
    command.add_argument("--stage", choices=(*STAGES, "all"), default="all")
    command.add_argument("--force", action="store_true")
    return command


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    args = parser().parse_args()
    scripts = Path(__file__).resolve().parent
    run_root = Path(args.run_root).expanduser().resolve()
    selected = STAGES if args.stage == "all" else (args.stage,)
    summary: list[dict[str, object]] = []
    for run_id in args.run_id:
        run_dir = run_root / run_id
        record = run_dir / "paper_record.json"
        if not record.is_file():
            raise SystemExit(f"Missing paper_record.json for {run_id}")
        outputs = {
            "evidence": run_dir / "evidence_pack.json",
            "assets": run_dir / "pdf_assets.json",
            "figures": run_dir / "figure_plan.json",
            "bundle": run_dir / "synthesis_bundle.json",
        }
        completed: list[str] = []
        skipped: list[str] = []
        try:
            for stage in selected:
                output = outputs[stage]
                if output.exists() and not args.force:
                    skipped.append(stage)
                    continue
                if stage == "evidence":
                    command = [
                        sys.executable,
                        str(scripts / "extract_evidence_v2.py"),
                        "--input",
                        str(record),
                        "--max-pages",
                        "0",
                        "--output",
                        str(output),
                    ]
                elif stage == "assets":
                    command = [
                        sys.executable,
                        str(scripts / "extract_pdf_assets_contract_v2.py"),
                        "--input",
                        str(record),
                        "--output",
                        str(output),
                        "--assets-dir",
                        str(run_dir / "assets"),
                        "--max-pages",
                        "0",
                    ]
                elif stage == "figures":
                    command = [
                        sys.executable,
                        str(scripts / "plan_figures_contract_v2.py"),
                        "--evidence",
                        str(outputs["evidence"]),
                        "--assets",
                        str(outputs["assets"]),
                        "--output",
                        str(output),
                        "--max-items",
                        "0",
                    ]
                else:
                    command = [
                        sys.executable,
                        str(scripts / "build_synthesis_bundle_v2.py"),
                        "--paper-record",
                        str(record),
                        "--evidence",
                        str(outputs["evidence"]),
                        "--figures",
                        str(outputs["figures"]),
                        "--assets",
                        str(outputs["assets"]),
                        "--output",
                        str(output),
                    ]
                _run(command)
                completed.append(stage)
            summary.append(
                {"run_id": run_id, "status": "pass", "completed": completed, "skipped": skipped}
            )
        except Exception as exc:
            summary.append(
                {
                    "run_id": run_id,
                    "status": "fail",
                    "completed": completed,
                    "skipped": skipped,
                    "failure": str(exc),
                }
            )
    print(json.dumps({"schema_version": "2.0", "runs": summary}, ensure_ascii=False, indent=2))
    if any(item["status"] == "fail" for item in summary):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

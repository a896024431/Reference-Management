#!/usr/bin/env python3
"""Run the only supported deterministic DeepPaperNote schema-v2 pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from contracts_v2 import artifact_header, emit_json, load_json_object, utc_run_id
from figure_contracts_v2 import normalize_figure_decisions, normalize_figure_manifest


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Title, DOI, URL, arXiv id, or local main PDF.")
    source.add_argument(
        "--input-record",
        help="Explicit JSON with title, main_pdf/documents, and supplement_pdfs.",
    )
    command.add_argument("--run-id", default="")
    command.add_argument("--workdir", default=".local/deeppapernote/runs")
    command.add_argument("--vault-root", default="")
    command.add_argument("--supplement", action="append", default=[])
    command.add_argument("--offline", action="store_true")
    command.add_argument("--max-pages", type=int, default=0, help="0 means all pages.")
    return command


def run(command: list[str], *, stage: str, log: list[dict[str, Any]]) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    log.append(
        {
            "stage": stage,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    )
    if result.returncode:
        raise RuntimeError(f"{stage} failed ({result.returncode}): {result.stderr.strip()}")


def write_plan_template(bundle: dict[str, Any], output: Path) -> None:
    artifact = artifact_header(
        "note_plan_template",
        paper_id=str(bundle["paper_id"]),
        run_id=str(bundle["run_id"]),
        status="degraded",
        failures=["pending_model_note_plan"],
    )
    artifact["note_plan"] = {
        "paper_type": bundle.get("paper_type", "generic"),
        "dominant_domain": "",
        "must_cover": [],
        "key_numbers": [],
        "real_comparisons": [],
        "section_plan": [],
        "evidence_ids": [],
    }
    emit_json(artifact, output)


def main() -> None:
    args = parser().parse_args()
    run_id = args.run_id or utc_run_id()
    run_dir = Path(args.workdir).expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    scripts = Path(__file__).resolve().parent
    python = sys.executable
    log: list[dict[str, Any]] = []
    paths = {
        "paper_record": run_dir / "paper_record.json",
        "evidence_pack": run_dir / "evidence_pack.json",
        "pdf_assets": run_dir / "pdf_assets.json",
        "figure_manifest": run_dir / "figure_manifest.json",
        "figure_plan": run_dir / "figure_plan.json",
        "figure_decisions": run_dir / "figure_decisions.json",
        "synthesis_bundle": run_dir / "synthesis_bundle.json",
        "note_plan_template": run_dir / "note_plan.template.json",
        "run_manifest": run_dir / "run_manifest.json",
    }
    try:
        if args.input_record:
            command = [
                python,
                str(scripts / "create_paper_record_v2.py"),
                "--input-record",
                args.input_record,
                "--run-id",
                run_id,
                "--output",
                str(paths["paper_record"]),
            ]
            if args.vault_root:
                command.extend(["--vault-root", args.vault_root])
            run(command, stage="create_paper_record", log=log)
        else:
            resolved = run_dir / "paper_record.resolved.json"
            metadata = run_dir / "paper_record.metadata.json"
            run(
                [
                    python,
                    str(scripts / "paper_record_v2.py"),
                    "--stage",
                    "resolve",
                    "--input",
                    str(args.input),
                    "--run-id",
                    run_id,
                    "--output",
                    str(resolved),
                ],
                stage="resolve_paper",
                log=log,
            )
            metadata_command = [
                python,
                str(scripts / "paper_record_v2.py"),
                "--stage",
                "metadata",
                "--input",
                str(resolved),
                "--output",
                str(metadata),
            ]
            if args.offline:
                metadata_command.append("--offline")
            run(metadata_command, stage="collect_metadata", log=log)
            fetch_command = [
                python,
                str(scripts / "paper_record_v2.py"),
                "--stage",
                "fetch",
                "--input",
                str(metadata),
                "--dest-dir",
                str(run_dir / "pdfs"),
                "--output",
                str(paths["paper_record"]),
            ]
            for supplement in args.supplement:
                fetch_command.extend(["--supplement", supplement])
            run(fetch_command, stage="fetch_pdf", log=log)

        run(
            [
                python,
                str(scripts / "extract_evidence_v2.py"),
                "--input",
                str(paths["paper_record"]),
                "--max-pages",
                str(args.max_pages),
                "--output",
                str(paths["evidence_pack"]),
            ],
            stage="extract_evidence",
            log=log,
        )
        run(
            [
                python,
                str(scripts / "extract_pdf_assets_v2.py"),
                "--input",
                str(paths["paper_record"]),
                "--assets-dir",
                str(run_dir / "assets"),
                "--max-pages",
                str(args.max_pages),
                "--output",
                str(paths["pdf_assets"]),
            ],
            stage="extract_pdf_assets",
            log=log,
        )
        manifest = normalize_figure_manifest(load_json_object(paths["pdf_assets"]))
        emit_json(manifest, paths["figure_manifest"])
        if manifest["status"] == "fail":
            raise RuntimeError("figure_manifest failed: " + "; ".join(manifest["failures"]))
        run(
            [
                python,
                str(scripts / "plan_figures_v2.py"),
                "--evidence",
                str(paths["evidence_pack"]),
                "--assets",
                str(paths["pdf_assets"]),
                "--output",
                str(paths["figure_plan"]),
            ],
            stage="plan_figures",
            log=log,
        )
        decisions = normalize_figure_decisions(
            load_json_object(paths["figure_plan"]),
            manifest=manifest,
            require_final=False,
        )
        emit_json(decisions, paths["figure_decisions"])
        run(
            [
                python,
                str(scripts / "build_synthesis_bundle_v2.py"),
                "--paper-record",
                str(paths["paper_record"]),
                "--evidence",
                str(paths["evidence_pack"]),
                "--figures",
                str(paths["figure_decisions"]),
                "--assets",
                str(paths["figure_manifest"]),
                "--output",
                str(paths["synthesis_bundle"]),
            ],
            stage="build_synthesis_bundle",
            log=log,
        )
        bundle = load_json_object(paths["synthesis_bundle"])
        write_plan_template(bundle, paths["note_plan_template"])
        report = artifact_header(
            "run_manifest",
            paper_id=str(bundle["paper_id"]),
            run_id=run_id,
            status="pass",
        )
        report.update(
            {
                "completion_stage": "synthesis_bundle",
                "downstream_pending": [
                    "model_note_plan",
                    "model_note_draft",
                    "lint_note_v2",
                    "quality_review",
                    "readability_review",
                    "figure_contact_sheet",
                    "figure_visual_review",
                    "publish_note_v2",
                    "rebuild_paper_navigation",
                    "lint_vault",
                ],
                "artifacts": {
                    key: str(value) for key, value in paths.items() if key != "run_manifest"
                },
                "stages": log,
            }
        )
        emit_json(report, paths["run_manifest"])
    except Exception as exc:
        paper_id = "unknown"
        if paths["paper_record"].exists():
            paper_id = str(load_json_object(paths["paper_record"]).get("paper_id", "unknown"))
        failed = artifact_header(
            "run_manifest",
            paper_id=paper_id,
            run_id=run_id,
            status="fail",
            failures=[str(exc)],
        )
        failed["stages"] = log
        emit_json(failed, paths["run_manifest"])
        raise SystemExit(str(exc)) from exc
    print(
        json.dumps(
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                **{key: str(value) for key, value in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

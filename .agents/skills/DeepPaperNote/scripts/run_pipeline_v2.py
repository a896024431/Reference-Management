#!/usr/bin/env python3
"""Run the deterministic schema-v2 DeepPaperNote pipeline for one paper."""

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
    source.add_argument(
        "--input",
        help="Title, DOI, URL, arXiv id, local PDF, or trusted resolve-stage JSON.",
    )
    source.add_argument(
        "--input-record",
        help="Explicit local JSON record with title, main_pdf/documents, and supplement_pdfs.",
    )
    command.add_argument("--run-id", default="")
    command.add_argument(
        "--workdir",
        default=".local/deeppapernote/runs",
        help="Base run directory; the run id is appended.",
    )
    command.add_argument(
        "--vault-root", default="", help="Used to derive safe vault-relative PDF links."
    )
    command.add_argument("--supplement", action="append", default=[])
    command.add_argument("--offline", action="store_true")
    command.add_argument("--max-pages", type=int, default=0, help="0 means all pages.")
    command.add_argument(
        "--skip-figures",
        action="store_true",
        help="Explicit diagnostic mode only; normal runs execute asset and figure planning.",
    )
    return command


def _run(command: list[str], *, stage: str, stage_log: list[dict[str, Any]]) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    stage_log.append(
        {
            "stage": stage,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Stage {stage} failed with exit code {result.returncode}: {result.stderr.strip()}"
        )


def _write_note_plan_template(bundle: dict[str, Any], path: Path) -> None:
    payload = artifact_header(
        "note_plan_template",
        paper_id=str(bundle["paper_id"]),
        run_id=str(bundle["run_id"]),
        status="degraded",
        failures=["pending_model_note_plan"],
    )
    payload["note_plan"] = {
        "paper_type": bundle.get("paper_type", "generic"),
        "dominant_domain": "",
        "must_cover": [],
        "key_numbers": [],
        "real_comparisons": [],
        "section_plan": [],
        "evidence_ids": [],
    }
    emit_json(payload, path)


def main() -> None:
    args = parser().parse_args()
    run_id = args.run_id or utc_run_id()
    base = Path(args.workdir).expanduser().resolve()
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    scripts = Path(__file__).resolve().parent
    python = sys.executable
    stage_log: list[dict[str, Any]] = []
    paper_record = run_dir / "paper_record.json"
    evidence = run_dir / "evidence_pack.json"
    raw_assets = run_dir / "assets.raw.json"
    manifest = run_dir / "figure_manifest.json"
    raw_plan = run_dir / "figures.raw.json"
    decisions = run_dir / "figure_decisions.json"
    bundle = run_dir / "synthesis_bundle.json"
    note_plan_template = run_dir / "note_plan.template.json"
    manifest_path = run_dir / "run_manifest.json"

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
                str(paper_record),
            ]
            if args.vault_root:
                command.extend(["--vault-root", args.vault_root])
            _run(command, stage="create_paper_record", stage_log=stage_log)
        else:
            resolved = run_dir / "paper_record.resolved.json"
            enriched = run_dir / "paper_record.metadata.json"
            _run(
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
                stage_log=stage_log,
            )
            metadata_command = [
                python,
                str(scripts / "paper_record_v2.py"),
                "--stage",
                "metadata",
                "--input",
                str(resolved),
                "--output",
                str(enriched),
            ]
            if args.offline:
                metadata_command.append("--offline")
            _run(metadata_command, stage="collect_metadata", stage_log=stage_log)
            fetch_command = [
                python,
                str(scripts / "paper_record_v2.py"),
                "--stage",
                "fetch",
                "--input",
                str(enriched),
                "--dest-dir",
                str(run_dir / "pdfs"),
                "--output",
                str(paper_record),
            ]
            for supplement in args.supplement:
                fetch_command.extend(["--supplement", supplement])
            _run(fetch_command, stage="fetch_pdf", stage_log=stage_log)

        _run(
            [
                python,
                str(scripts / "extract_evidence_v2.py"),
                "--input",
                str(paper_record),
                "--max-pages",
                str(args.max_pages),
                "--output",
                str(evidence),
            ],
            stage="extract_evidence",
            stage_log=stage_log,
        )

        if args.skip_figures:
            record = load_json_object(paper_record)
            empty_manifest = artifact_header(
                "figure_manifest",
                paper_id=record["paper_id"],
                run_id=record["run_id"],
                status="degraded",
                failures=["figure_stages_explicitly_skipped"],
            )
            empty_manifest["assets"] = []
            empty_decisions = artifact_header(
                "figure_decisions",
                paper_id=record["paper_id"],
                run_id=record["run_id"],
                status="degraded",
                failures=["figure_stages_explicitly_skipped"],
            )
            empty_decisions["decisions"] = []
            emit_json(empty_manifest, manifest)
            emit_json(empty_decisions, decisions)
        else:
            _run(
                [
                    python,
                    str(scripts / "extract_pdf_assets_v2.py"),
                    "--input",
                    str(paper_record),
                    "--output",
                    str(raw_assets),
                    "--assets-dir",
                    str(run_dir / "assets"),
                ],
                stage="extract_pdf_assets",
                stage_log=stage_log,
            )
            canonical_manifest = normalize_figure_manifest(load_json_object(raw_assets))
            emit_json(canonical_manifest, manifest)
            if canonical_manifest["status"] == "fail":
                raise RuntimeError(
                    "Figure manifest validation failed: "
                    + "; ".join(canonical_manifest["failures"])
                )
            record = load_json_object(paper_record)
            _run(
                [
                    python,
                    str(scripts / "plan_figures_v2.py"),
                    "--input",
                    str(paper_record),
                    "--evidence",
                    str(evidence),
                    "--assets",
                    str(raw_assets),
                    "--paper-id",
                    str(record["paper_id"]),
                    "--run-id",
                    str(record["run_id"]),
                    "--output",
                    str(raw_plan),
                ],
                stage="plan_figures",
                stage_log=stage_log,
            )
            canonical_decisions = normalize_figure_decisions(
                load_json_object(raw_plan),
                manifest=canonical_manifest,
                require_final=False,
            )
            emit_json(canonical_decisions, decisions)

        _run(
            [
                python,
                str(scripts / "build_synthesis_bundle_v2.py"),
                "--paper-record",
                str(paper_record),
                "--evidence",
                str(evidence),
                "--figures",
                str(decisions),
                "--assets",
                str(manifest),
                "--output",
                str(bundle),
            ],
            stage="build_synthesis_bundle",
            stage_log=stage_log,
        )
        bundle_record = load_json_object(bundle)
        _write_note_plan_template(bundle_record, note_plan_template)
        run_manifest = artifact_header(
            "run_manifest",
            paper_id=str(bundle_record["paper_id"]),
            run_id=run_id,
            status="pass",
        )
        run_manifest.update(
            {
                "completion_stage": "synthesis_bundle",
                "downstream_pending": [
                    "model_note_plan",
                    "model_note_draft",
                    "quality_review",
                    "lint",
                    "final_readability_review",
                    "final_figure_confirmation",
                    "atomic_publish",
                ],
                "artifacts": {
                    "paper_record": str(paper_record),
                    "evidence_pack": str(evidence),
                    "figure_manifest": str(manifest),
                    "figure_decisions": str(decisions),
                    "synthesis_bundle": str(bundle),
                    "note_plan_template": str(note_plan_template),
                },
                "stages": stage_log,
            }
        )
        emit_json(run_manifest, manifest_path)
    except Exception as exc:
        fallback = artifact_header(
            "run_manifest",
            paper_id="unknown",
            run_id=run_id,
            status="fail",
            failures=[str(exc)],
        )
        try:
            if paper_record.exists():
                fallback["paper_id"] = str(
                    load_json_object(paper_record).get("paper_id", "unknown")
                )
        except Exception:
            pass
        fallback["stages"] = stage_log
        emit_json(fallback, manifest_path)
        raise SystemExit(str(exc)) from exc

    print(
        json.dumps(
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "paper_record": str(paper_record),
                "evidence_pack": str(evidence),
                "figure_manifest": str(manifest),
                "figure_decisions": str(decisions),
                "synthesis_bundle": str(bundle),
                "run_manifest": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

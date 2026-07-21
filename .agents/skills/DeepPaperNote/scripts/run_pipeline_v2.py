#!/usr/bin/env python3
"""Run the only supported deterministic DeepPaperNote schema-v2 pipeline."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_v2_artifact,
    utc_run_id,
    validate_run_id,
)
from figure_contracts_v2 import normalize_figure_decisions, normalize_figure_manifest


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--input",
        required=True,
        help="Local main PDF already mirrored under 文献/.",
    )
    command.add_argument("--run-id", default="")
    command.add_argument(
        "--workdir",
        default="",
        help="Run-local directory; defaults to <vault>/.local/deeppapernote/runs.",
    )
    command.add_argument("--vault-root", required=True)
    command.add_argument("--supplement", action="append", default=[])
    command.add_argument(
        "--offline",
        action="store_true",
        required=True,
        help="Required: process only local PDFs and disable metadata queries and downloads.",
    )
    command.add_argument("--max-pages", type=int, default=0, help="0 means all pages.")
    return command


def validate_environment(args: argparse.Namespace) -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("DeepPaperNote requires Python 3.10 or newer")
    if sys.flags.utf8_mode != 1:
        raise SystemExit("DeepPaperNote requires Python UTF-8 mode (PYTHONUTF8=1)")
    if importlib.util.find_spec("fitz") is None:
        raise SystemExit("PyMuPDF/fitz is required before starting a run")
    try:
        importlib.import_module("fitz")
    except Exception as exc:
        raise SystemExit(f"PyMuPDF/fitz cannot be imported: {exc}") from exc
    if args.max_pages < 0:
        raise SystemExit("--max-pages must be non-negative")
    root = Path(args.vault_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"--vault-root is not a directory: {root}")
    library = root / "文献"
    if not library.is_dir():
        raise SystemExit(f"Vault does not contain the mirrored 文献/ library: {library}")

    def local_pdf(value: str, *, label: str) -> Path:
        path = Path(value).expanduser().resolve()
        try:
            relative = path.relative_to(library.resolve())
        except ValueError as exc:
            raise SystemExit(f"{label} must be a local PDF under 文献/: {path}") from exc
        if not path.is_file() or path.suffix.casefold() != ".pdf" or len(relative.parts) < 3:
            raise SystemExit(
                f"{label} must be a PDF in 文献/<collection>/<paper>/: {path}"
            )
        return path

    main_pdf = local_pdf(args.input, label="--input")
    seen = {main_pdf}
    for index, supplement in enumerate(args.supplement, start=1):
        supplement_pdf = local_pdf(supplement, label=f"--supplement[{index}]")
        if supplement_pdf.parent != main_pdf.parent:
            raise SystemExit("All supplementary PDFs must be in the main PDF's paper directory")
        if supplement_pdf in seen:
            raise SystemExit("Main and supplementary PDFs must not be repeated")
        seen.add(supplement_pdf)

    local_runs = (root / ".local" / "deeppapernote" / "runs").resolve()
    workdir = Path(args.workdir).expanduser().resolve() if args.workdir else local_runs
    try:
        workdir.relative_to(local_runs)
    except ValueError as exc:
        raise SystemExit(
            "--workdir must stay under <vault>/.local/deeppapernote/runs/"
        ) from exc
    args.input = str(main_pdf)
    args.supplement = [str(Path(value).expanduser().resolve()) for value in args.supplement]
    args.vault_root = str(root)
    args.workdir = str(workdir)


def require_pass(path: Path, *, artifact_type: str) -> dict[str, Any]:
    artifact = load_json_object(path)
    require_v2_artifact(artifact, artifact_type=artifact_type, allow_statuses={"pass"})
    return artifact


def run(
    command: list[str],
    *,
    stage: str,
    log: list[dict[str, Any]],
    artifact_path: Path | None = None,
) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    entry = {
        "stage": stage,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    log.append(entry)
    if result.returncode:
        artifact_failures: list[str] = []
        if artifact_path is not None and artifact_path.is_file():
            try:
                artifact = load_json_object(artifact_path)
                failures = artifact.get("failures", [])
                if isinstance(failures, list):
                    artifact_failures = [
                        str(failure) for failure in failures if str(failure).strip()
                    ]
            except Exception:
                pass
        if artifact_failures:
            entry["artifact_failures"] = artifact_failures
        detail = "; ".join(artifact_failures)
        detail = detail or result.stderr.strip() or result.stdout.strip() or "unknown failure"
        raise RuntimeError(f"{stage} failed ({result.returncode}): {detail}")


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
        "key_claims": [],
        "figure_intents": [],
    }
    emit_json(artifact, output)


def main() -> None:
    args = parser().parse_args()
    validate_environment(args)
    run_id = validate_run_id(args.run_id or utc_run_id())
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
        resolved = run_dir / "paper_record.resolved.json"
        metadata = run_dir / "paper_record.metadata.json"
        resolve_command = [
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
            "--vault-root",
            args.vault_root,
            "--offline",
        ]
        run(resolve_command, stage="resolve_paper", log=log, artifact_path=resolved)
        metadata_command = [
            python,
            str(scripts / "paper_record_v2.py"),
            "--stage",
            "metadata",
            "--input",
            str(resolved),
            "--output",
            str(metadata),
            "--offline",
        ]
        run(
            metadata_command,
            stage="collect_metadata",
            log=log,
            artifact_path=metadata,
        )
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
            "--vault-root",
            args.vault_root,
            "--offline",
        ]
        for supplement in args.supplement:
            fetch_command.extend(["--supplement", supplement])
        run(
            fetch_command,
            stage="record_local_pdfs",
            log=log,
            artifact_path=paths["paper_record"],
        )
        require_pass(paths["paper_record"], artifact_type="paper_record")

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
            artifact_path=paths["evidence_pack"],
        )
        require_pass(paths["evidence_pack"], artifact_type="evidence_pack")
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
            artifact_path=paths["pdf_assets"],
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
            artifact_path=paths["figure_plan"],
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
            artifact_path=paths["synthesis_bundle"],
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
                    "validate_note_plan_v2",
                    "model_note_draft",
                    "lint_note_v2",
                    "quality_review",
                    "readability_review",
                    "figure_contact_sheet",
                    "figure_visual_review",
                    "publish_note_v2",
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

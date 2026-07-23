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


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--input",
        required=True,
        help="Local main PDF already mirrored under 文献/.",
    )
    command.add_argument("--run-id", default="")
    command.add_argument("--vault-root", required=True)
    command.add_argument("--supplement", action="append", default=[])
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
        if (
            not path.is_file()
            or path.suffix.casefold() != ".pdf"
            or len(relative.parts) < 3
            or relative.parts[0].casefold() == "Zotero已删除".casefold()
        ):
            raise SystemExit(f"{label} must be an active PDF in 文献/<collection>/<paper>/: {path}")
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

    args.input = str(main_pdf)
    args.supplement = [str(Path(value).expanduser().resolve()) for value in args.supplement]
    args.vault_root = str(root)


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


def main() -> None:
    args = parser().parse_args()
    validate_environment(args)
    run_id = validate_run_id(args.run_id or utc_run_id())
    run_dir = Path(args.vault_root).resolve() / ".local" / "deeppapernote" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    staging_dir = run_dir / "staging"
    scripts = Path(__file__).resolve().parent
    python = sys.executable
    log: list[dict[str, Any]] = []
    paths = {
        "paper_record": run_dir / "paper_record.json",
        "evidence_pack": run_dir / "evidence_pack.json",
        "visual_pages": run_dir / "visual_pages.json",
        "synthesis_bundle": run_dir / "synthesis_bundle.json",
        "note_plan": run_dir / "note_plan.json",
        "run_manifest": run_dir / "run_manifest.json",
    }
    try:
        record_command = [
            python,
            str(scripts / "paper_record_v2.py"),
            "--input",
            str(args.input),
            "--run-id",
            run_id,
            "--vault-root",
            args.vault_root,
            "--output",
            str(paths["paper_record"]),
        ]
        for supplement in args.supplement:
            record_command.extend(["--supplement", supplement])
        run(
            record_command,
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
                str(scripts / "render_visual_pages_v2.py"),
                "--paper-record",
                str(paths["paper_record"]),
                "--evidence",
                str(paths["evidence_pack"]),
                "--run-dir",
                str(run_dir),
                "--output",
                str(paths["visual_pages"]),
            ],
            stage="render_visual_pages",
            log=log,
            artifact_path=paths["visual_pages"],
        )
        run(
            [
                python,
                str(scripts / "build_synthesis_bundle_v2.py"),
                "--paper-record",
                str(paths["paper_record"]),
                "--evidence",
                str(paths["evidence_pack"]),
                "--visual-pages",
                str(paths["visual_pages"]),
                "--output",
                str(paths["synthesis_bundle"]),
            ],
            stage="build_synthesis_bundle",
            log=log,
            artifact_path=paths["synthesis_bundle"],
        )
        bundle = load_json_object(paths["synthesis_bundle"])
        staging_dir.mkdir(parents=True, exist_ok=False)
        report = artifact_header(
            "run_manifest",
            paper_id=str(bundle["paper_id"]),
            run_id=run_id,
            status="pass",
        )
        report.update(
            {
                "completion_stage": "synthesis_bundle",
                "staging_dir": str(staging_dir),
                "downstream_pending": [
                    "model_note_plan",
                    "model_note_draft",
                    "second_read",
                    "publish_note_v2",
                ],
                "artifacts": {
                    key: str(value)
                    for key, value in paths.items()
                    if key != "run_manifest" and value.exists()
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
                "staging_dir": str(staging_dir),
                **{key: str(value) for key, value in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

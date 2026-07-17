#!/usr/bin/env python3
"""Rebuild the seven non-golden migration runs with canonical v2 entrypoints.

This runner is intentionally corpus-specific.  It validates the migration index,
keeps the existing paper identity records, scans every PDF page by default, and
rebuilds deterministic artifacts without touching the formal Research tree.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    validate_paper_record_artifact,
)
from figure_contracts_v2 import (
    normalize_figure_decisions,
    normalize_figure_manifest,
)

CANONICAL_RUNS = (
    "migration-01-electron",
    "migration-02-enhanced",
    "migration-03-hard-soft",
    "migration-04-nanopatterning",
    "migration-06-slow",
    "migration-07-spontaneous",
    "migration-08-tunable",
)

GOLDEN_TITLES = {
    "Nanoscale electrostatic control in ultraclean van der Waals "
    "heterostructures by local anodic oxidation of graphite gates",
    "Universal chiral Luttinger liquid behavior in a graphene fractional "
    "quantum Hall point contact",
}

REBUILD_FILES = (
    "evidence_pack.json",
    "pdf_assets.json",
    "figure_plan.json",
    "figure_manifest.json",
    "figure_decisions.json",
    "synthesis_bundle.json",
    "canonicalization_manifest.json",
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--runs-root",
        default=".local/deeppapernote/runs",
        help="Directory containing the migration-* run folders.",
    )
    command.add_argument(
        "--index",
        default=".local/deeppapernote/migration-inputs/papers/index.json",
        help="Nine-paper migration input index used for identity validation.",
    )
    command.add_argument(
        "--report",
        default=".local/deeppapernote/migration-inputs/canonical-corpus-report-v2.json",
    )
    command.add_argument(
        "--run",
        action="append",
        default=[],
        help="Optional migration run name. Repeat to select a subset.",
    )
    command.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Per-document page limit; 0 means every page.",
    )
    command.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="Figure target limit; 0 keeps all detected targets.",
    )
    return command


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_index(index_path: Path, run_dirs: list[Path]) -> dict[str, str]:
    index = load_json(index_path)
    records = index.get("records", [])
    if not isinstance(records, list) or len(records) != 9:
        raise ValueError("migration index must contain exactly nine records")
    title_to_input: dict[str, str] = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("migration index contains a non-object record")
        title = str(item.get("title", "")).strip()
        input_record = str(item.get("input_record", "")).strip()
        if not title or not input_record or title in title_to_input:
            raise ValueError(f"invalid or duplicate migration title: {title!r}")
        if not Path(input_record).is_file():
            raise FileNotFoundError(f"migration input record missing: {input_record}")
        title_to_input[title] = input_record

    selected_titles: set[str] = set()
    for run_dir in run_dirs:
        paper_record = load_json(run_dir / "paper_record.json")
        validate_paper_record_artifact(paper_record)
        if str(paper_record["run_id"]) != run_dir.name:
            raise ValueError(f"run identity mismatch: {run_dir.name} != {paper_record['run_id']}")
        title = str(paper_record["paper_record"]["metadata"].get("title", ""))
        if title not in title_to_input:
            raise ValueError(f"run title is absent from migration index: {title}")
        if title in GOLDEN_TITLES:
            raise ValueError(f"golden pilot selected by corpus runner: {title}")
        if title in selected_titles:
            raise ValueError(f"duplicate selected paper title: {title}")
        selected_titles.add(title)
    return title_to_input


def run_stage(
    command: list[str],
    *,
    stage: str,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log = {
        "stage": stage,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    if result.returncode not in allowed_returncodes:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{stage} failed ({result.returncode}): {message}")
    return log


def backup_existing(run_dir: Path, stamp: str) -> Path | None:
    backup_root = run_dir / ".canonical-backups" / stamp
    moved = False
    for name in (*REBUILD_FILES, "assets"):
        source = run_dir / name
        if not source.exists():
            continue
        destination = backup_root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        moved = True
    return backup_root if moved else None


def restore_backup(run_dir: Path, backup_root: Path | None) -> None:
    for name in (*REBUILD_FILES, "assets"):
        current = run_dir / name
        if current.exists():
            if not within(current, run_dir):
                raise RuntimeError(f"unsafe rollback target: {current}")
            if current.is_dir():
                shutil.rmtree(current)
            else:
                current.unlink()
        if backup_root is not None:
            saved = backup_root / name
            if saved.exists():
                os.replace(saved, current)


def unique_strings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def collect_metrics(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    assets: dict[str, Any],
    figures: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    paper_id, run_id = require_same_identity(paper_record, evidence, assets, figures, bundle)
    record = paper_record["paper_record"]
    documents = record.get("documents", [])
    declared_pages = Counter()
    document_counts = Counter()
    for document in documents:
        role = str(document.get("role", ""))
        declared_pages[role] += int(document.get("pages", 0) or 0)
        document_counts[role] += 1

    processed_pages = Counter()
    for page in assets.get("page_assets", []):
        processed_pages[str(page.get("document_role", ""))] += 1

    pack = evidence.get("evidence_pack", {})
    coverage = pack.get("coverage", {})
    manifest = normalize_figure_manifest(assets)
    decisions = normalize_figure_decisions(figures, manifest=manifest, require_final=False)
    manifest_assets = manifest.get("assets", [])
    usable_asset_ids = {
        str(asset.get("asset_id", ""))
        for asset in manifest_assets
        if str(asset.get("quality_signals", {}).get("visual_quality_status", "")) == "usable"
    }
    rejected_asset_ids = {
        str(asset.get("asset_id", ""))
        for asset in manifest_assets
        if str(asset.get("quality_signals", {}).get("visual_quality_status", "")).startswith(
            "reject"
        )
    }
    decision_items = decisions.get("decisions", [])
    recommended_usable = sum(
        str(item.get("recommended_asset_id", "")) in usable_asset_ids
        and str(item.get("recommended_asset_id", "")) not in set(item.get("rejected_asset_ids", []))
        for item in decision_items
    )
    decision_counts = Counter(str(item.get("decision", "unknown")) for item in decision_items)
    pending_confirmation = sum(
        str(item.get("decision_reason", "")) == "awaiting_semantic_confirmation"
        for item in decision_items
    )

    ocr_used_pages = [
        f"{page.get('document_id')} p.{page.get('page_number')}"
        for page in assets.get("page_assets", [])
        if page.get("ocr_used")
    ]
    textless_pages = [
        f"{page.get('document_id')} p.{page.get('page_number')}"
        for page in assets.get("page_assets", [])
        if str(page.get("text_extraction_method", "")) == "none"
    ]
    artifact_failures: list[Any] = []
    for artifact in (evidence, assets, figures, bundle):
        artifact_failures.extend(artifact.get("failures", []))
    failures = unique_strings(artifact_failures)
    statuses = {
        "evidence": str(evidence.get("status", "fail")),
        "pdf_assets": str(assets.get("status", "fail")),
        "figure_plan": str(figures.get("status", "fail")),
        "synthesis_bundle": str(bundle.get("status", "fail")),
    }
    if "fail" in statuses.values():
        overall_status = "fail"
    elif "degraded" in statuses.values():
        overall_status = "degraded"
    else:
        overall_status = "pass"

    return {
        "paper_id": paper_id,
        "run_id": run_id,
        "title": record.get("metadata", {}).get("title", ""),
        "paper_type": pack.get("paper_type", "generic"),
        "paper_type_rationale": pack.get("paper_type_rationale", ""),
        "status": overall_status,
        "artifact_statuses": statuses,
        "documents": {
            "main_count": document_counts["main"],
            "supplement_count": document_counts["supplement"],
            "main_pages_declared": declared_pages["main"],
            "supplement_pages_declared": declared_pages["supplement"],
            "main_pages_processed": processed_pages["main"],
            "supplement_pages_processed": processed_pages["supplement"],
        },
        "evidence": {
            "units": len(pack.get("evidence_units", [])),
            "quality": pack.get("evidence_quality", "unknown"),
            "coverage_ratio": coverage.get("ratio", 0),
            "coverage_required": coverage.get("required", []),
            "coverage_available": coverage.get("available", []),
            "coverage_missing": coverage.get("missing", []),
        },
        "figures": {
            "candidates": len(manifest_assets),
            "usable_candidates": len(usable_asset_ids),
            "rejected_candidates": len(rejected_asset_ids),
            "targets": len(decision_items),
            "targets_with_usable_recommendation": recommended_usable,
            "pending_semantic_confirmation": pending_confirmation,
            "decision_counts": dict(decision_counts),
        },
        "ocr": {
            "available": bool(assets.get("ocr_available")),
            "used": bool(ocr_used_pages),
            "used_pages": ocr_used_pages,
            "needs_ocr": bool(textless_pages),
            "textless_pages": textless_pages,
        },
        "errors": failures,
    }


def rebuild_run(
    run_dir: Path,
    *,
    scripts: Path,
    max_pages: int,
    max_items: int,
    stamp: str,
    input_record: str,
) -> dict[str, Any]:
    paper_record_path = run_dir / "paper_record.json"
    paper_record = load_json_object(paper_record_path)
    validate_paper_record_artifact(paper_record)
    paths = {
        "evidence": run_dir / "evidence_pack.json",
        "assets": run_dir / "pdf_assets.json",
        "figures": run_dir / "figure_plan.json",
        "manifest": run_dir / "figure_manifest.json",
        "decisions": run_dir / "figure_decisions.json",
        "bundle": run_dir / "synthesis_bundle.json",
        "run_manifest": run_dir / "canonicalization_manifest.json",
    }
    backup_root = backup_existing(run_dir, stamp)
    stage_log: list[dict[str, Any]] = []
    try:
        stage_log.append(
            run_stage(
                [
                    sys.executable,
                    str(scripts / "extract_evidence_contract_v2.py"),
                    "--input",
                    str(paper_record_path),
                    "--max-pages",
                    str(max_pages),
                    "--output",
                    str(paths["evidence"]),
                ],
                stage="extract_evidence_contract_v2",
                allowed_returncodes=(0, 2),
            )
        )
        stage_log.append(
            run_stage(
                [
                    sys.executable,
                    str(scripts / "extract_pdf_assets_contract_v2.py"),
                    "--input",
                    str(paper_record_path),
                    "--assets-dir",
                    str(run_dir / "assets"),
                    "--max-pages",
                    str(max_pages),
                    "--output",
                    str(paths["assets"]),
                ],
                stage="extract_pdf_assets_contract_v2",
            )
        )
        stage_log.append(
            run_stage(
                [
                    sys.executable,
                    str(scripts / "plan_figures_contract_v2.py"),
                    "--evidence",
                    str(paths["evidence"]),
                    "--assets",
                    str(paths["assets"]),
                    "--max-items",
                    str(max_items),
                    "--output",
                    str(paths["figures"]),
                ],
                stage="plan_figures_contract_v2",
            )
        )
        stage_log.append(
            run_stage(
                [
                    sys.executable,
                    str(scripts / "build_synthesis_bundle_v2.py"),
                    "--paper-record",
                    str(paper_record_path),
                    "--evidence",
                    str(paths["evidence"]),
                    "--figures",
                    str(paths["figures"]),
                    "--assets",
                    str(paths["assets"]),
                    "--output",
                    str(paths["bundle"]),
                ],
                stage="build_synthesis_bundle_v2",
                allowed_returncodes=(0, 2),
            )
        )

        evidence = load_json_object(paths["evidence"])
        assets = load_json_object(paths["assets"])
        figures = load_json_object(paths["figures"])
        bundle = load_json_object(paths["bundle"])
        manifest = normalize_figure_manifest(assets)
        decisions = normalize_figure_decisions(figures, manifest=manifest, require_final=False)
        emit_json(manifest, paths["manifest"])
        emit_json(decisions, paths["decisions"])
        metrics = collect_metrics(paper_record, evidence, assets, figures, bundle)
        run_manifest = artifact_header(
            "corpus_canonicalization_manifest",
            paper_id=str(paper_record["paper_id"]),
            run_id=str(paper_record["run_id"]),
            status=str(metrics["status"]),
            failures=list(metrics["errors"]),
        )
        run_manifest.update(
            {
                "source_input_record": input_record,
                "full_page_extraction": max_pages == 0,
                "max_pages": max_pages,
                "max_figure_items": max_items,
                "backup_dir": str(backup_root) if backup_root else "",
                "artifacts": {
                    key: str(value) for key, value in paths.items() if key != "run_manifest"
                },
                "stages": stage_log,
                "metrics": metrics,
            }
        )
        emit_json(run_manifest, paths["run_manifest"])
        metrics["backup_dir"] = str(backup_root) if backup_root else ""
        return metrics
    except Exception:
        restore_backup(run_dir, backup_root)
        raise


def main() -> None:
    args = parser().parse_args()
    runs_root = Path(args.runs_root).expanduser().resolve()
    index_path = Path(args.index).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    selected = tuple(args.run) if args.run else CANONICAL_RUNS
    unknown = sorted(set(selected) - set(CANONICAL_RUNS))
    if unknown:
        raise SystemExit(f"unsupported or golden run selection: {unknown}")
    if len(selected) != len(set(selected)):
        raise SystemExit("duplicate --run selection")
    run_dirs = [runs_root / name for name in selected]
    missing = [str(path) for path in run_dirs if not path.is_dir()]
    if missing:
        raise SystemExit(f"migration run directory missing: {missing}")
    title_to_input = validate_index(index_path, run_dirs)
    scripts = Path(__file__).resolve().parent
    stamp = utc_stamp()
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for run_dir in run_dirs:
        paper_record = load_json(run_dir / "paper_record.json")
        title = str(paper_record["paper_record"]["metadata"]["title"])
        try:
            metrics = rebuild_run(
                run_dir,
                scripts=scripts,
                max_pages=args.max_pages,
                max_items=args.max_items,
                stamp=stamp,
                input_record=title_to_input[title],
            )
        except Exception as exc:
            message = f"{run_dir.name}: {exc}"
            failures.append(message)
            metrics = {
                "paper_id": paper_record.get("paper_id", "unknown"),
                "run_id": run_dir.name,
                "title": title,
                "status": "fail",
                "errors": [str(exc)],
            }
        results.append(metrics)

    statuses = Counter(str(item.get("status", "fail")) for item in results)
    if failures or statuses["fail"]:
        report_status = "fail"
    elif statuses["degraded"]:
        report_status = "degraded"
    else:
        report_status = "pass"
    report = artifact_header(
        "canonical_corpus_report",
        paper_id="vault-corpus",
        run_id=f"canonical-corpus-{stamp}",
        status=report_status,
        failures=failures,
    )
    report.update(
        {
            "index": str(index_path),
            "runs_root": str(runs_root),
            "full_page_extraction": args.max_pages == 0,
            "selected_runs": list(selected),
            "golden_runs_excluded": True,
            "summary": {
                "papers": len(results),
                "status_counts": dict(statuses),
                "main_documents": sum(
                    int(item.get("documents", {}).get("main_count", 0)) for item in results
                ),
                "supplement_documents": sum(
                    int(item.get("documents", {}).get("supplement_count", 0)) for item in results
                ),
            },
            "papers": results,
        }
    )
    emit_json(report, report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report_status == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

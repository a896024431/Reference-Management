#!/usr/bin/env python3
"""Finalize canonical corpus runs with the release figure planner.

The input runs must already contain canonical ``paper_record.json``,
``evidence_pack.json`` and ``pdf_assets.json`` artifacts.  This command backs
up and rebuilds only figure planning and the downstream synthesis bundle.
It never reads or writes the formal Research tree.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    require_v2_artifact,
    validate_paper_record_artifact,
)
from figure_contracts_v2 import (
    normalize_figure_decisions,
    normalize_figure_manifest,
)
from run_corpus_canonical_v2 import (
    CANONICAL_RUNS,
    collect_metrics,
    run_stage,
    utc_stamp,
    within,
)

RELEASE_FILES = (
    "figure_plan.json",
    "figure_manifest.json",
    "figure_decisions.json",
    "synthesis_bundle.json",
    "figure_release_manifest.json",
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--runs-root", default=".local/deeppapernote/runs")
    command.add_argument(
        "--run",
        action="append",
        default=[],
        help="Repeat to select migration runs; defaults to all seven.",
    )
    command.add_argument("--max-items", type=int, default=0)
    command.add_argument(
        "--report",
        default=".local/deeppapernote/migration-inputs/release-figure-corpus-report-v2.json",
    )
    return command


def _backup_release_files(run_dir: Path, stamp: str) -> Path | None:
    backup_root = run_dir / ".figure-release-backups" / stamp
    moved = False
    for name in RELEASE_FILES:
        source = run_dir / name
        if not source.exists():
            continue
        destination = backup_root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        moved = True
    return backup_root if moved else None


def _restore_release_files(run_dir: Path, backup_root: Path | None) -> None:
    for name in RELEASE_FILES:
        current = run_dir / name
        if current.exists():
            if not within(current, run_dir):
                raise RuntimeError(f"unsafe release rollback target: {current}")
            if current.is_dir():
                shutil.rmtree(current)
            else:
                current.unlink()
        if backup_root is not None:
            saved = backup_root / name
            if saved.exists():
                os.replace(saved, current)


def _release_metrics(
    paper_record: dict[str, Any],
    evidence: dict[str, Any],
    assets: dict[str, Any],
    figures: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    metrics = collect_metrics(paper_record, evidence, assets, figures, bundle)
    manifest = normalize_figure_manifest(assets)
    decisions = normalize_figure_decisions(figures, manifest=manifest, require_final=False)
    rejected = {
        str(asset.get("asset_id", ""))
        for asset in manifest.get("assets", [])
        if str(asset.get("quality_signals", {}).get("visual_quality_status", "")) == "reject"
    }
    decision_items = [item for item in decisions.get("decisions", []) if isinstance(item, dict)]
    metrics["release_figure_gate"] = {
        "planner": figures.get("planner", ""),
        "caption_bridge": figures.get("caption_bridge", {}),
        "reject_candidates": len(rejected),
        "reject_selected": sum(
            str(item.get("selected_asset_id", "")) in rejected
            and bool(item.get("selected_asset_id"))
            for item in decision_items
        ),
        "reject_recommended": sum(
            str(item.get("recommended_asset_id", "")) in rejected
            and bool(item.get("recommended_asset_id"))
            for item in decision_items
        ),
    }
    return metrics


def finalize_run(
    run_dir: Path,
    *,
    scripts: Path,
    max_items: int,
    stamp: str,
) -> dict[str, Any]:
    paths = {
        "paper_record": run_dir / "paper_record.json",
        "evidence": run_dir / "evidence_pack.json",
        "assets": run_dir / "pdf_assets.json",
        "figures": run_dir / "figure_plan.json",
        "manifest": run_dir / "figure_manifest.json",
        "decisions": run_dir / "figure_decisions.json",
        "bundle": run_dir / "synthesis_bundle.json",
        "release_manifest": run_dir / "figure_release_manifest.json",
    }
    paper_record = load_json_object(paths["paper_record"])
    evidence = load_json_object(paths["evidence"])
    assets = load_json_object(paths["assets"])
    validate_paper_record_artifact(paper_record)
    require_v2_artifact(evidence, artifact_type="evidence_pack")
    require_v2_artifact(assets, artifact_type="pdf_assets")
    require_same_identity(paper_record, evidence, assets)
    backup_root = _backup_release_files(run_dir, stamp)
    stage_log: list[dict[str, Any]] = []
    try:
        stage_log.append(
            run_stage(
                [
                    sys.executable,
                    str(scripts / "plan_figures_release_v2.py"),
                    "--evidence",
                    str(paths["evidence"]),
                    "--assets",
                    str(paths["assets"]),
                    "--max-items",
                    str(max_items),
                    "--output",
                    str(paths["figures"]),
                ],
                stage="plan_figures_release_v2",
            )
        )
        figures = load_json_object(paths["figures"])
        manifest = normalize_figure_manifest(assets)
        decisions = normalize_figure_decisions(figures, manifest=manifest, require_final=False)
        emit_json(manifest, paths["manifest"])
        emit_json(decisions, paths["decisions"])
        stage_log.append(
            run_stage(
                [
                    sys.executable,
                    str(scripts / "build_synthesis_bundle_v2.py"),
                    "--paper-record",
                    str(paths["paper_record"]),
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
        bundle = load_json_object(paths["bundle"])
        metrics = _release_metrics(paper_record, evidence, assets, figures, bundle)
        release_manifest = artifact_header(
            "figure_release_manifest",
            paper_id=str(paper_record["paper_id"]),
            run_id=str(paper_record["run_id"]),
            status=str(metrics["status"]),
            failures=list(metrics.get("errors", [])),
        )
        release_manifest.update(
            {
                "backup_dir": str(backup_root) if backup_root else "",
                "max_figure_items": max_items,
                "stages": stage_log,
                "metrics": metrics,
            }
        )
        emit_json(release_manifest, paths["release_manifest"])
        metrics["backup_dir"] = str(backup_root) if backup_root else ""
        return metrics
    except Exception:
        _restore_release_files(run_dir, backup_root)
        raise


def main() -> None:
    args = parser().parse_args()
    selected = tuple(args.run) if args.run else CANONICAL_RUNS
    unknown = sorted(set(selected) - set(CANONICAL_RUNS))
    if unknown:
        raise SystemExit(f"unsupported or golden run selection: {unknown}")
    if len(selected) != len(set(selected)):
        raise SystemExit("duplicate --run selection")
    runs_root = Path(args.runs_root).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    scripts = Path(__file__).resolve().parent
    stamp = utc_stamp()
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for name in selected:
        run_dir = runs_root / name
        if not run_dir.is_dir():
            failures.append(f"{name}: run directory missing")
            continue
        try:
            results.append(
                finalize_run(
                    run_dir,
                    scripts=scripts,
                    max_items=args.max_items,
                    stamp=stamp,
                )
            )
        except Exception as exc:
            failures.append(f"{name}: {exc}")

    status_counts = Counter(str(item.get("status", "fail")) for item in results)
    if failures or status_counts["fail"]:
        status = "fail"
    elif status_counts["degraded"]:
        status = "degraded"
    else:
        status = "pass"
    report = artifact_header(
        "release_figure_corpus_report",
        paper_id="vault-corpus",
        run_id=f"release-figure-corpus-{stamp}",
        status=status,
        failures=failures,
    )
    report.update(
        {
            "runs_root": str(runs_root),
            "selected_runs": list(selected),
            "planner_entrypoint": str(scripts / "plan_figures_release_v2.py"),
            "max_figure_items": args.max_items,
            "summary": {
                "papers": len(results),
                "status_counts": dict(status_counts),
            },
            "papers": results,
        }
    )
    emit_json(report, report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if status == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

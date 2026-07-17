from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from figure_contracts_v2 import (
    build_figure_asset_identity,
    make_figure_decisions,
    make_figure_manifest,
    sha256_bytes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATERIALIZE_SCRIPT = PROJECT_ROOT / "scripts" / "materialize_figure_asset_v2.py"


def test_cli_accepts_canonical_v2_pass_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source_bytes = b"canonical-v2-figure"
    source.write_bytes(source_bytes)
    digest = sha256_bytes(source_bytes)
    asset_id, filename, bbox_hash = build_figure_asset_identity(
        document_id="main",
        page_number=2,
        label="Fig. 1",
        bbox=[10.0, 20.0, 300.0, 220.0],
        content_sha256=digest,
    )
    asset = {
        "asset_id": asset_id,
        "document_id": "main",
        "page_number": 2,
        "label": "Fig. 1",
        "caption_text": "Fig. 1. Verified device overview.",
        "filename": filename,
        "path": str(source),
        "ext": "png",
        "bbox_pt": [10.0, 20.0, 300.0, 220.0],
        "bbox_sha256": bbox_hash,
        "file_sha256": digest,
        "extraction_level": "figure",
        "quality_signals": {"visual_quality_status": "usable"},
    }
    manifest = make_figure_manifest(
        paper_id="paper-test",
        run_id="run-test",
        assets=[asset],
    )
    decisions = make_figure_decisions(
        paper_id="paper-test",
        run_id="run-test",
        decisions=[
            {
                "target_id": "main|fig 1",
                "display_label": "Fig. 1",
                "decision": "inserted",
                "selected_asset_id": asset_id,
                "candidate_asset_ids": [asset_id],
                "rejected_asset_ids": [],
            }
        ],
    )
    assert manifest["status"] == decisions["status"] == "pass"

    manifest_path = tmp_path / "figure_manifest.json"
    decisions_path = tmp_path / "figure_decisions.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    destination = tmp_path / "images"

    result = subprocess.run(
        [
            sys.executable,
            str(MATERIALIZE_SCRIPT),
            "--manifest",
            str(manifest_path),
            "--decisions",
            str(decisions_path),
            "--target-id",
            "main|fig 1",
            "--destination-dir",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "2.0"
    assert payload["artifact_type"] == "materialized_figure"
    assert payload["status"] == "pass"
    assert payload["failures"] == []
    assert (destination / filename).read_bytes() == source_bytes

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import publish_note_v2
import pytest
from contracts_v2 import artifact_header, load_json_object, sha256_text
from publish_note_v2 import (
    _rollback_after_audit_failure,
    archive_publish_audit,
    publish_transaction,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def _make_pipeline_pdf(path: Path) -> Path:
    pages = [
        (
            "I. INTRODUCTION\n"
            "We investigate an open problem in graphene quantum Hall transport and "
            "ask how a controlled point contact changes edge conductance. "
            "This introduction establishes the physical problem and motivation."
        ),
        (
            "II. EXPERIMENTAL METHODS\n"
            "We fabricate a graphene device, apply gate voltage, and measure "
            "conductance at 20 mK with a calibrated low-noise protocol. "
            "The device geometry and measurement procedure are recorded."
        ),
        (
            "III. RESULTS AND DISCUSSION\n"
            "We observe that conductance increases by 10 percent in the controlled "
            "setting. The repeated measurement supports the result while device "
            "inhomogeneity remains a limitation and an alternative explanation."
        ),
    ]
    document = fitz.open()
    try:
        document.set_metadata({"title": "Graphene quantum Hall transport experiment"})
        for text in pages:
            page = document.new_page()
            page.insert_textbox(fitz.Rect(48, 48, 548, 760), text, fontsize=10)
        document.save(str(path))
    finally:
        document.close()
    return path


def _run_pipeline(
    *,
    input_record: Path,
    workdir: Path,
    vault_root: Path,
    run_id: str,
    max_pages: int,
    supplements: list[Path] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPTS / "run_pipeline_v2.py"),
        "--input-record",
        str(input_record),
        "--offline",
        "--run-id",
        run_id,
        "--workdir",
        str(workdir),
        "--vault-root",
        str(vault_root),
        "--max-pages",
        str(max_pages),
    ]
    for supplement in supplements or []:
        command.extend(["--supplement", str(supplement)])
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_real_pdf_offline_pipeline_passes_and_truncation_rolls_up_failure(
    tmp_path: Path,
) -> None:
    pdf = _make_pipeline_pdf(tmp_path / "paper.pdf")
    supplement = _make_pipeline_pdf(tmp_path / "supplement.pdf")
    input_record = tmp_path / "input.json"
    input_record.write_text(
        json.dumps(
            {
                "title": "Graphene quantum Hall transport experiment",
                "main_pdf": str(pdf),
            }
        ),
        encoding="utf-8",
    )
    workdir = tmp_path / "runs"

    passed = _run_pipeline(
        input_record=input_record,
        workdir=workdir,
        vault_root=tmp_path,
        run_id="integration-pass",
        max_pages=0,
        supplements=[supplement],
    )

    assert passed.returncode == 0, passed.stderr
    passed_dir = workdir / "integration-pass"
    for name in (
        "paper_record.json",
        "evidence_pack.json",
        "pdf_assets.json",
        "figure_manifest.json",
        "figure_plan.json",
        "figure_decisions.json",
        "synthesis_bundle.json",
        "run_manifest.json",
    ):
        assert load_json_object(passed_dir / name)["status"] == "pass"
    template = load_json_object(passed_dir / "note_plan.template.json")["note_plan"]
    assert {
        "evidence_ids",
        "must_cover",
        "key_claims",
        "key_numbers",
        "real_comparisons",
        "section_plan",
        "figure_intents",
    }.issubset(template)
    documents = load_json_object(passed_dir / "paper_record.json")["paper_record"]["documents"]
    assert [document["role"] for document in documents] == ["main", "supplement"]
    assert [document["vault_path"] for document in documents] == [
        "paper.pdf",
        "supplement.pdf",
    ]

    truncated = _run_pipeline(
        input_record=input_record,
        workdir=workdir,
        vault_root=tmp_path,
        run_id="integration-truncated",
        max_pages=1,
    )

    assert truncated.returncode != 0
    failed_dir = workdir / "integration-truncated"
    run_manifest = load_json_object(failed_dir / "run_manifest.json")
    evidence = load_json_object(failed_dir / "evidence_pack.json")
    assert run_manifest["status"] == "fail"
    assert evidence["status"] == "fail"
    assert any(failure.startswith("document_truncated:") for failure in evidence["failures"])


def _make_staging(root: Path, text: str) -> Path:
    staging = root / "staging"
    (staging / "images").mkdir(parents=True)
    (staging / "笔记.md").write_text(text, encoding="utf-8")
    return staging


def _make_existing_target(vault: Path, folder: str, text: str) -> Path:
    target = vault / "Research" / folder
    (target / "images").mkdir(parents=True)
    (target / "笔记.md").write_text(text, encoding="utf-8")
    return target


def test_publish_transaction_can_be_rolled_back_after_audit_failure(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "Atomic Test Paper"
    staging = _make_staging(tmp_path, "new note")
    _make_existing_target(vault, folder, "old note")
    release = {"folder_name": folder}
    backup_root = tmp_path / "rollback"

    target, backup = publish_transaction(
        staging_dir=staging,
        vault=vault,
        backup_root=backup_root,
        release=release,
    )

    assert (target / "笔记.md").read_text(encoding="utf-8") == "new note"
    assert backup is not None
    _rollback_after_audit_failure(target=target, backup=backup, vault=vault)
    assert (target / "笔记.md").read_text(encoding="utf-8") == "old note"


def test_archive_publish_audit_is_atomic_and_preserves_previous_on_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "Audit Test Paper"
    target = _make_existing_target(vault, folder, "published note")
    run_id = "audit-atomic-test"
    release = {
        "paper_id": "paper:audit",
        "run_id": run_id,
        "folder_name": folder,
        "note_sha256": sha256_text("published note"),
    }
    artifacts = {
        "paper_record": artifact_header(
            "paper_record",
            paper_id=release["paper_id"],
            run_id=run_id,
        )
    }
    report = artifact_header(
        "publish_report",
        paper_id=release["paper_id"],
        run_id=run_id,
    )

    audit = archive_publish_audit(
        vault=vault,
        target=target,
        artifacts=artifacts,
        contact_sheet={"kind": "contact-sheet"},
        visual_review={"kind": "visual-review"},
        release=release,
        report=report,
    )
    original_snapshot = (audit / "snapshot.json").read_bytes()

    real_replace = os.replace

    def fail_new_audit(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            source_path.name.startswith(f".{run_id}.audit-")
            and ".audit-old-" not in source_path.name
            and destination_path == audit
        ):
            raise OSError("simulated audit replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(publish_note_v2.os, "replace", fail_new_audit)

    with pytest.raises(OSError, match="simulated"):
        archive_publish_audit(
            vault=vault,
            target=target,
            artifacts=artifacts,
            contact_sheet={"kind": "new-contact-sheet"},
            visual_review={"kind": "new-visual-review"},
            release=release,
            report=report,
        )

    assert audit.is_dir()
    assert (audit / "snapshot.json").read_bytes() == original_snapshot


@pytest.mark.parametrize(
    "script_name",
    [
        "build_figure_contact_sheet_v2.py",
        "build_synthesis_bundle_v2.py",
        "create_input_record.py",
        "create_paper_record_v2.py",
        "extract_evidence_v2.py",
        "extract_pdf_assets_v2.py",
        "lint_note_v2.py",
        "lint_vault.py",
        "locate_zotero_attachment.py",
        "paper_record_v2.py",
        "plan_figures_v2.py",
        "publish_note_v2.py",
        "rebuild_paper_navigation.py",
        "record_figure_visual_review_v2.py",
        "record_note_review_v2.py",
        "run_pipeline_v2.py",
        "validate_note_plan_v2.py",
    ],
)
def test_retained_cli_help(script_name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script_name), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

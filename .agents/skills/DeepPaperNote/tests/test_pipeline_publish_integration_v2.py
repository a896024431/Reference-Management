from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import paper_record_v2
import publish_note_v2
import pytest
import run_pipeline_v2
from contracts_v2 import ContractError, artifact_header, load_json_object, sha256_text
from publish_note_v2 import (
    _rollback_release_state,
    archive_publish_audit,
    publish_transaction,
    resolve_publish_target,
    validate_existing_audit_identity,
    validate_operational_paths,
    validate_published_target,
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
    input_pdf: Path,
    vault_root: Path,
    run_id: str,
    max_pages: int,
    supplements: list[Path] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPTS / "run_pipeline_v2.py"),
        "--input",
        str(input_pdf),
        "--run-id",
        run_id,
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


def test_real_pdf_pipeline_passes_and_truncation_rolls_up_failure(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pipeline_pdf(paper_dir / "paper.pdf")
    supplement = _make_pipeline_pdf(paper_dir / "supplement.pdf")
    workdir = vault / ".local" / "deeppapernote" / "runs"

    passed = _run_pipeline(
        input_pdf=pdf,
        vault_root=vault,
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
    run_manifest = load_json_object(passed_dir / "run_manifest.json")
    staging = passed_dir / "staging"
    assert staging.is_dir()
    assert (staging / "images").is_dir()
    assert list((staging / "images").iterdir()) == []
    assert run_manifest["staging_dir"] == str(staging)
    assert run_manifest["downstream_pending"][-1] == "publish_note_v2"
    assert "rebuild_paper_navigation" not in run_manifest["downstream_pending"]
    assert "lint_vault" not in run_manifest["downstream_pending"]
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
        "文献/QPC/Graphene quantum Hall transport experiment/paper.pdf",
        "文献/QPC/Graphene quantum Hall transport experiment/supplement.pdf",
    ]

    truncated = _run_pipeline(
        input_pdf=pdf,
        vault_root=vault,
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
    assert any("document_truncated:" in failure for failure in run_manifest["failures"])
    assert "document_truncated:" in truncated.stderr


def test_pipeline_formal_entry_rejects_nonmirrored_inputs_and_legacy_input_records(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    mirrored = vault / "文献" / "QPC" / "Paper" / "main.pdf"
    mirrored.parent.mkdir(parents=True)
    mirrored.write_bytes(b"not parsed because validation fails first")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"local but not mirrored")
    archived = vault / "文献" / "Zotero已删除" / "QPC" / "Old Paper" / "main.pdf"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"local archive")

    rejected_input = _run_pipeline(
        input_pdf=outside,
        vault_root=vault,
        run_id="reject-outside",
        max_pages=0,
    )
    rejected_archive = _run_pipeline(
        input_pdf=archived,
        vault_root=vault,
        run_id="reject-archive",
        max_pages=0,
    )

    assert rejected_input.returncode != 0
    assert "must be a local PDF under 文献/" in rejected_input.stderr
    assert rejected_archive.returncode != 0
    assert "must be an active PDF" in rejected_archive.stderr
    pipeline_help = run_pipeline_v2.parser().format_help()
    assert "--input-record" not in pipeline_help
    assert "--workdir" not in pipeline_help
    assert "--offline" not in pipeline_help
    record_help = paper_record_v2.parser().format_help()
    assert "--stage" not in record_help
    assert "--dest-dir" not in record_help
    assert "--offline" not in record_help


def test_pipeline_rejects_supplement_from_another_paper_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    main = vault / "文献" / "QPC" / "Paper A" / "main.pdf"
    supplement = vault / "文献" / "QPC" / "Paper B" / "si.pdf"
    main.parent.mkdir(parents=True)
    supplement.parent.mkdir(parents=True)
    main.write_bytes(b"main")
    supplement.write_bytes(b"si")

    result = _run_pipeline(
        input_pdf=main,
        vault_root=vault,
        run_id="reject-cross-paper-si",
        max_pages=0,
        supplements=[supplement],
    )

    assert result.returncode != 0
    assert "All supplementary PDFs must be in the main PDF's paper directory" in result.stderr


def _make_staging(root: Path, text: str) -> Path:
    staging = root / "staging"
    (staging / "images").mkdir(parents=True)
    (staging / "笔记.md").write_bytes(text.encode("utf-8"))
    return staging


def _make_existing_target(vault: Path, folder: str, text: str) -> Path:
    target = vault / "文献" / "QPC" / folder
    (target / "images").mkdir(parents=True)
    (target / "笔记.md").write_text(text, encoding="utf-8")
    (target / "main.pdf").write_bytes(b"source PDF must be preserved")
    return target


def test_publish_target_is_derived_from_the_local_main_pdf_parent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target = vault / "文献" / "制备工艺" / "EFLAO" / "Target Paper"
    target.mkdir(parents=True)
    main = target / "main.pdf"
    supplement = target / "si.pdf"
    main.write_bytes(b"main")
    supplement.write_bytes(b"si")
    record = {
        "paper_record": {
            "documents": [
                {
                    "role": "main",
                    "path": str(main.resolve()),
                    "vault_path": "文献/制备工艺/EFLAO/Target Paper/main.pdf",
                },
                {
                    "role": "supplement",
                    "path": str(supplement.resolve()),
                    "vault_path": "文献/制备工艺/EFLAO/Target Paper/si.pdf",
                },
            ]
        }
    }

    assert resolve_publish_target(
        vault=vault, paper_record=record, release={"title": "Target Paper"}
    ) == target.resolve()

    other = vault / "文献" / "制备工艺" / "EFLAO" / "Other Paper" / "si.pdf"
    other.parent.mkdir()
    other.write_bytes(b"other")
    record["paper_record"]["documents"][1].update(
        {
            "path": str(other.resolve()),
            "vault_path": "文献/制备工艺/EFLAO/Other Paper/si.pdf",
        }
    )
    with pytest.raises(ContractError, match="same paper directory"):
        resolve_publish_target(vault=vault, paper_record=record, release={"title": "Target Paper"})


def test_publish_transaction_can_be_rolled_back_after_audit_failure(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "Atomic Test Paper"
    staging = _make_staging(tmp_path, "new\r\nnote\r\n")
    old_note = (
        '---\ntitle: "Atomic Test Paper"\nauthors:\n  - A. Author\n'
        'year: 2025\n---\nold note'
    )
    target = _make_existing_target(vault, folder, old_note)
    navigation = vault / "文献" / "论文导航.md"
    navigation.write_bytes(b"old navigation\r\n")
    release = {
        "folder_name": folder,
        "title": "Atomic Test Paper",
        "authors": ["a. author"],
        "year": "2025",
    }
    backup_root = vault / ".local" / "rollback"

    target, backup = publish_transaction(
        staging_dir=staging,
        vault=vault,
        target=target,
        backup_root=backup_root,
        release=release,
    )

    assert (target / "笔记.md").read_bytes() == b"new\nnote\n"
    assert not (target / "images").exists()
    assert (target / "main.pdf").read_bytes() == b"source PDF must be preserved"
    assert backup is not None
    navigation.write_bytes(b"new navigation\n")
    _rollback_release_state(
        target=target,
        backup=backup,
        vault=vault,
        previous_navigation=b"old navigation\r\n",
    )
    assert (target / "笔记.md").read_text(encoding="utf-8") == old_note
    assert navigation.read_bytes() == b"old navigation\r\n"
    assert (target / "main.pdf").read_bytes() == b"source PDF must be preserved"


def test_publish_transaction_refuses_sanitized_title_collision(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "A B"
    staging = _make_staging(tmp_path, "new note\n")
    existing_note = '---\ntitle: "A:B"\n---\nexisting note'
    target = _make_existing_target(vault, folder, existing_note)

    with pytest.raises(ContractError, match="collides with an existing paper directory"):
        publish_transaction(
            staging_dir=staging,
            vault=vault,
            target=target,
            backup_root=vault / ".local" / "rollback",
            release={"folder_name": folder, "title": "A?B"},
        )

    assert (target / "笔记.md").read_text(encoding="utf-8") == existing_note
    assert (staging / "笔记.md").is_file()


def test_publish_transaction_refuses_same_title_with_different_doi(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "Shared Paper Title"
    staging = _make_staging(tmp_path, "new note\n")
    existing_note = (
        '---\ntitle: "Shared Paper Title"\ndoi: "10.1000/existing"\n---\nexisting note'
    )
    target = _make_existing_target(vault, folder, existing_note)

    with pytest.raises(ContractError, match="collides with an existing paper directory"):
        publish_transaction(
            staging_dir=staging,
            vault=vault,
            target=target,
            backup_root=vault / ".local" / "rollback",
            release={
                "folder_name": folder,
                "title": "Shared Paper Title",
                "doi": "https://doi.org/10.1000/incoming",
            },
        )

    assert (target / "笔记.md").read_text(encoding="utf-8") == existing_note


def test_publish_transaction_refuses_unidentified_same_title_with_different_authors(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "Unidentified Shared Title"
    staging = _make_staging(tmp_path, "new note\n")
    existing_note = (
        '---\ntitle: "Unidentified Shared Title"\nauthors:\n  - Existing Author\n'
        'year: 2025\n---\nexisting note'
    )
    target = _make_existing_target(vault, folder, existing_note)

    with pytest.raises(ContractError, match="collides with an existing paper directory"):
        publish_transaction(
            staging_dir=staging,
            vault=vault,
            target=target,
            backup_root=vault / ".local" / "rollback",
            release={
                "folder_name": folder,
                "title": "Unidentified Shared Title",
                "authors": ["Different Author"],
                "year": "2025",
            },
        )

    assert (target / "笔记.md").read_text(encoding="utf-8") == existing_note


def test_prepare_failure_removes_partial_publish_directory(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    staging = _make_staging(tmp_path, "new note\n")
    old_note = (
        '---\ntitle: "Prepare Failure"\nauthors:\n  - A. Author\n'
        "year: 2025\n---\nold note\n"
    )
    target = _make_existing_target(vault, "Prepare Failure", old_note)
    (staging / "images" / "candidate.png").write_bytes(b"candidate")
    monkeypatch.setattr(
        publish_note_v2.shutil,
        "copytree",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )

    with pytest.raises(OSError, match="copy failed"):
        publish_transaction(
            staging_dir=staging,
            vault=vault,
            target=target,
            backup_root=vault / ".local" / "rollback",
            release={
                "folder_name": "Prepare Failure",
                "title": "Prepare Failure",
                "authors": ["a. author"],
                "year": "2025",
            },
        )

    assert target.is_dir()
    assert (target / "笔记.md").read_text(encoding="utf-8") == old_note
    assert (target / "main.pdf").read_bytes() == b"source PDF must be preserved"


def test_post_commit_validation_rechecks_note_and_image_hashes(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "笔记.md").write_text("actual note\n", encoding="utf-8", newline="\n")
    with pytest.raises(ContractError, match="Published note hash differs"):
        validate_published_target(
            target,
            {
                "note_sha256": sha256_text("different note\n"),
                "image_names": [],
                "materialized": [],
            },
        )

    note = "![[images/fig.png]]\n"
    (target / "笔记.md").write_text(note, encoding="utf-8", newline="\n")
    image_dir = target / "images"
    image_dir.mkdir()
    image_dir.joinpath("fig.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c"
            "020000000b4944415478da6364f80f00010501012718e3660000000049454e44"
            "ae426082"
        )
    )
    with pytest.raises(ContractError, match="Published image hash mismatch"):
        validate_published_target(
            target,
            {
                "note_sha256": sha256_text(note),
                "image_names": ["fig.png"],
                "materialized": [{"filename": "fig.png", "file_sha256": "0" * 64}],
            },
        )


def test_operational_paths_cannot_write_reader_facing_vault_content(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "文献").mkdir(parents=True)
    with pytest.raises(ContractError, match="backup_root"):
        validate_operational_paths(
            vault=vault,
            backup_root=vault / "文献" / "rollback",
            output=None,
        )
    with pytest.raises(ContractError, match="backup_root must stay under .local"):
        validate_operational_paths(
            vault=vault,
            backup_root=tmp_path / "outside-rollback",
            output=None,
        )
    with pytest.raises(ContractError, match="must stay under .local"):
        validate_operational_paths(
            vault=vault,
            backup_root=vault / ".local" / "rollback",
            output=vault / "文献" / "论文导航.md",
        )
    validate_operational_paths(
        vault=vault,
        backup_root=vault / ".local" / "rollback",
        output=vault / ".local" / "reports" / "publish.json",
    )
    with pytest.raises(ContractError, match="must not overwrite any publish audit"):
        validate_operational_paths(
            vault=vault,
            backup_root=vault / ".local" / "rollback",
            output=(
                vault
                / ".local"
                / "deeppapernote"
                / "published"
                / "another-run"
                / "snapshot.json"
            ),
        )


def test_publish_transaction_rejects_a_backup_inside_the_paper_library(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = _make_existing_target(
        vault,
        "Backup Boundary",
        '---\ntitle: "Backup Boundary"\nauthors:\n  - A. Author\nyear: 2025\n---\nold\n',
    )
    with pytest.raises(ContractError, match="backup_root"):
        publish_transaction(
            staging_dir=_make_staging(tmp_path, "new note\n"),
            vault=vault,
            target=target,
            backup_root=target / "rollback",
            release={
                "title": "Backup Boundary",
                "authors": ["a. author"],
                "year": "2025",
            },
        )


def test_existing_audit_run_id_cannot_be_reused_for_another_paper(tmp_path: Path) -> None:
    audit = tmp_path / "published" / "run-reused"
    audit.mkdir(parents=True)
    (audit / "snapshot.json").write_text(
        json.dumps(
            artifact_header(
                "published_audit",
                paper_id="paper:existing",
                run_id="run-reused",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="collides with an existing publish audit"):
        validate_existing_audit_identity(
            audit,
            {"paper_id": "paper:incoming", "run_id": "run-reused"},
        )


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
    report["navigation_sha256"] = "1" * 64
    report["vault_lint_summary"] = {"errors": 0, "warnings": 0}

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


def test_old_audit_cleanup_failure_is_only_a_warning(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    folder = "Audit Cleanup Test Paper"
    target = _make_existing_target(vault, folder, "published note")
    run_id = "audit-cleanup-test"
    release = {
        "paper_id": "paper:audit-cleanup",
        "run_id": run_id,
        "folder_name": folder,
        "note_sha256": sha256_text("published note"),
    }
    artifacts = {
        "paper_record": artifact_header(
            "paper_record", paper_id=release["paper_id"], run_id=run_id
        )
    }
    report = artifact_header(
        "publish_report", paper_id=release["paper_id"], run_id=run_id
    )
    report["navigation_sha256"] = "2" * 64
    report["vault_lint_summary"] = {"errors": 0, "warnings": 0}
    kwargs = {
        "vault": vault,
        "target": target,
        "artifacts": artifacts,
        "contact_sheet": {"kind": "contact-sheet"},
        "visual_review": {"kind": "visual-review"},
        "release": release,
        "report": report,
    }
    audit = archive_publish_audit(**kwargs)
    original_remove = publish_note_v2._safe_remove_tree

    def fail_old_cleanup(path: Path, *, allowed_root: Path) -> None:
        if ".audit-old-" in path.name:
            raise OSError("simulated old audit cleanup failure")
        original_remove(path, allowed_root=allowed_root)

    monkeypatch.setattr(publish_note_v2, "_safe_remove_tree", fail_old_cleanup)

    with pytest.warns(RuntimeWarning, match="old audit backup"):
        replaced = archive_publish_audit(**kwargs)

    assert replaced == audit
    assert audit.is_dir()


@pytest.mark.parametrize(
    "script_name",
    [
        "build_figure_contact_sheet_v2.py",
        "build_synthesis_bundle_v2.py",
        "extract_evidence_v2.py",
        "extract_pdf_assets_v2.py",
        "lint_note_v2.py",
        "lint_vault.py",
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

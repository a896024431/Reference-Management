from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import fitz
import publish_note_v2
import pytest
import render_visual_pages_v2
from contracts_v2 import ContractError, artifact_header, emit_json, load_json_object, sha256_text
from render_visual_pages_v2 import render_visual_pages
from validate_note_plan_v2 import build_note_plan_artifact

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def _make_pdf(path: Path) -> Path:
    pages = [
        "I. INTRODUCTION\nThis work asks how a graphene point contact changes conductance.",
        (
            "II. EXPERIMENTAL METHODS\nWe measure conductance at 20 mK with calibrated gates.\n"
            "Figure 1: Device geometry and measurement circuit."
        ),
        (
            "III. RESULTS AND DISCUSSION\nConductance increases by 10 percent. The result has "
            "an alternative explanation from device inhomogeneity.\n"
            "Figure 2: Conductance response."
        ),
    ]
    document = fitz.open()
    try:
        document.set_metadata({"title": "Graphene quantum Hall transport experiment"})
        for text in pages:
            page = document.new_page()
            page.insert_textbox(fitz.Rect(48, 48, 548, 760), text, fontsize=10)
        document.save(path)
    finally:
        document.close()
    return path


def _run_pipeline(pdf: Path, vault: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "run_pipeline_v2.py"),
            "--input",
            str(pdf),
            "--vault-root",
            str(vault),
            "--run-id",
            run_id,
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _plan(bundle: dict) -> dict:
    ids = [item["evidence_id"] for item in bundle["evidence_units"][:3]]
    return {
        "paper_type": bundle["paper_type"],
        "dominant_domain": "condensed-matter-physics",
        "evidence_ids": ids,
        "must_cover": [{"topic": "量子霍尔点接触", "evidence_ids": [ids[0]]}],
        "key_claims": [
            {"claim": "研究问题", "evidence_ids": [ids[0]]},
            {"claim": "实验方法", "evidence_ids": [ids[1]]},
            {"claim": "主要结果", "evidence_ids": [ids[2]]},
        ],
        "key_numbers": [],
        "real_comparisons": [],
        "section_plan": [
            {"section": "研究问题", "evidence_ids": [ids[0]]},
            {"section": "实验体系与测量", "evidence_ids": [ids[1]]},
            {"section": "主要结果与证据链", "evidence_ids": [ids[2]]},
        ],
    }


def _note() -> str:
    return """---
type: paper
title: Graphene quantum Hall transport experiment
title_zh: 石墨烯量子霍尔输运实验
authors:
  - A. Researcher
year: 2025
venue: Physical Review Test
domain: condensed-matter-physics
topics:
  - quantum-hall
  - graphene
paper_type: experimental_physics
evidence_level: full_text
note_status: polished
aliases:
  - Graphene quantum Hall transport experiment
  - 石墨烯量子霍尔输运实验
tags:
  - papers/physics/condensed-matter
---

# 石墨烯量子霍尔输运实验

## 30 秒速览

论文研究石墨烯量子霍尔点接触中的输运调控。

## 关键结论

- 研究将点接触作为可控边缘输运元件〔主文 p. 1〕。
- 实验在 20 mK 下用校准栅极测量电导〔主文 p. 2〕。
- 受控条件下电导提高约 10%，但器件非均匀性仍是替代解释〔主文 p. 3〕。

## 适用边界

结论适用于该低温器件与校准条件，不能直接外推到所有石墨烯器件。

## 快速入口与页面导航

- [[#研究问题]]
- [[#主要结果与证据链]]

## 原文摘要翻译

本文研究石墨烯量子霍尔输运中的可控点接触。

## 创新点

把器件控制、低温测量与替代解释放在同一证据链中讨论。

## 研究问题

核心问题是点接触怎样改变边缘通道输运〔主文 p. 1〕。

## 实验体系与测量

器件在低温下由校准栅极调控，并测量电导〔主文 p. 2〕。

## 主要结果与证据链

电导提高约 10%，同时必须保留器件非均匀性的替代解释〔主文 p. 3〕。

## 解释、替代解释与证据边界

观测支持受控输运变化，但不足以单独排除器件非均匀性。

## 局限与未决问题

仍需在更多器件上复现实验并区分替代机制。

## 可复用结论

点接触实验应同时报告控制变量、直接观测和替代解释。

## 相关论文

暂无唯一可确认的本地关联论文。

## 我的笔记

后续可比较不同栅极几何的控制范围。

## 引用

Graphene quantum Hall transport experiment.
"""


def _review(bundle: dict) -> dict:
    ids = [item["evidence_id"] for item in bundle["evidence_units"][:3]]
    return {
        "reviewer": "second-reader",
        "review_origin": "subagent",
        "scores": {
            "factual_fidelity": 5,
            "completeness": 5,
            "domain_expression": 5,
            "clarity": 5,
            "chinese_naturalness": 5,
            "navigability": 5,
            "traceability": 5,
        },
        "unresolved_issues": [],
        "passages_checked": [
            {
                "heading": "关键结论",
                "quote": "研究将点接触作为可控边缘输运元件",
                "evidence_ids": [ids[0]],
            },
            {
                "heading": "关键结论",
                "quote": "实验在 20 mK 下用校准栅极测量电导",
                "evidence_ids": [ids[1]],
            },
            {
                "heading": "关键结论",
                "quote": "受控条件下电导提高约 10%",
                "evidence_ids": [ids[2]],
            },
        ],
    }


def test_pipeline_renders_visual_pages_without_creating_note_images(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pdf(paper_dir / "paper.pdf")

    result = _run_pipeline(pdf, vault, "text-only-run")

    assert result.returncode == 0, result.stderr
    run_dir = vault / ".local" / "deeppapernote" / "runs" / "text-only-run"
    assert (run_dir / "staging").is_dir()
    assert not (run_dir / "staging" / "images").exists()
    visual_pages = load_json_object(run_dir / "visual_pages.json")
    assert visual_pages["status"] == "pass"
    assert len(visual_pages["pages"]) == 2
    for page in visual_pages["pages"]:
        assert (run_dir / page["path"]).is_file()
    bundle = load_json_object(run_dir / "synthesis_bundle.json")
    assert bundle["visual_pages"]["artifact_type"] == "visual_pages"
    assert all(
        field not in bundle
        for field in (
            "evidence_by_type",
            "section_texts",
            "candidate_chunks",
            "note_plan_contract",
            "writing_contract",
        )
    )


def test_visual_reader_hashes_each_source_pdf_once_before_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pdf(paper_dir / "paper.pdf")
    assert _run_pipeline(pdf, vault, "batched-visual-hash").returncode == 0
    run_dir = vault / ".local" / "deeppapernote" / "runs" / "batched-visual-hash"
    paper_record = load_json_object(run_dir / "paper_record.json")
    evidence = load_json_object(run_dir / "evidence_pack.json")
    shutil.rmtree(run_dir / "visual-pages")
    original_sha256_file = render_visual_pages_v2.sha256_file
    hash_calls: list[Path] = []

    def count_hashes(path: str | Path) -> str:
        hash_calls.append(Path(path).resolve())
        return original_sha256_file(path)

    monkeypatch.setattr(render_visual_pages_v2, "sha256_file", count_hashes)
    artifact = render_visual_pages(paper_record, evidence, run_dir=run_dir)

    assert len(artifact["pages"]) == 2
    assert hash_calls == [pdf.resolve(), pdf.resolve()]


def test_visual_reader_rejects_a_pdf_changed_after_evidence_extraction(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pdf(paper_dir / "paper.pdf")
    assert _run_pipeline(pdf, vault, "changed-visual-source").returncode == 0
    run_dir = vault / ".local" / "deeppapernote" / "runs" / "changed-visual-source"
    paper_record = load_json_object(run_dir / "paper_record.json")
    evidence = load_json_object(run_dir / "evidence_pack.json")
    shutil.rmtree(run_dir / "visual-pages")
    with pdf.open("ab") as handle:
        handle.write(b"\nchanged after evidence extraction")

    with pytest.raises(ContractError, match="changed before reading"):
        render_visual_pages(paper_record, evidence, run_dir=run_dir)

    assert not (run_dir / "visual-pages").exists()


def test_finalizer_publishes_a_text_only_note_and_rebuilds_navigation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pdf(paper_dir / "paper.pdf")
    legacy_images = paper_dir / "images"
    legacy_images.mkdir()
    legacy_image = legacy_images / "legacy.png"
    legacy_image.write_bytes(b"legacy reader asset")
    assert _run_pipeline(pdf, vault, "publish-text-only").returncode == 0
    run_dir = vault / ".local" / "deeppapernote" / "runs" / "publish-text-only"
    bundle = load_json_object(run_dir / "synthesis_bundle.json")
    emit_json(build_note_plan_artifact(_plan(bundle), bundle), run_dir / "note_plan.json")
    note = _note()
    (run_dir / "staging" / "笔记.md").write_text(note, encoding="utf-8", newline="\n")
    (run_dir / "second_review.input.json").write_text(
        json.dumps(_review(bundle), ensure_ascii=False), encoding="utf-8"
    )

    report = publish_note_v2.finalize_run(
        vault=vault,
        run_id="publish-text-only",
        author="note-author",
        backup_root=vault / ".local" / "deeppapernote" / "rollback" / "publish-text-only",
        output=None,
    )

    assert report["target_lint_status"] == "pass"
    assert (paper_dir / "笔记.md").is_file()
    assert legacy_image.read_bytes() == b"legacy reader asset"
    assert (vault / "文献" / "论文导航.md").is_file()
    assert (vault / ".local" / "deeppapernote" / "published" / "publish-text-only").is_dir()


def test_audit_cleanup_failure_only_warns_after_new_audit_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "文献" / "QPC" / "Paper"
    target.mkdir(parents=True)
    note = target / "笔记.md"
    note.write_text("# Paper\n", encoding="utf-8")
    release = {
        "paper_id": "title:test",
        "run_id": "audit-cleanup-warning",
        "note_sha256": sha256_text(note.read_text(encoding="utf-8")),
    }
    audit_target = publish_note_v2._audit_target(vault, release["run_id"])
    audit_target.mkdir(parents=True)
    (audit_target / "old.json").write_text("{}\n", encoding="utf-8")
    artifact = artifact_header(
        "lint_report", paper_id=release["paper_id"], run_id=release["run_id"]
    )

    def fail_old_backup_cleanup(path: Path, *, allowed_root: Path) -> None:
        raise OSError(f"cannot clean {path.name}")

    monkeypatch.setattr(publish_note_v2, "_safe_remove_tree", fail_old_backup_cleanup)
    with pytest.warns(RuntimeWarning, match="old audit backup remains"):
        result = publish_note_v2.archive_publish_audit(
            vault=vault,
            target=target,
            artifacts={"lint_report": artifact},
            release=release,
            report={"navigation_sha256": "0" * 64},
        )

    assert (result / "snapshot.json").is_file()
    assert list(result.parent.glob(".audit-cleanup-warning.audit-old-*"))


def test_finalizer_warns_when_final_report_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pdf(paper_dir / "paper.pdf")
    run_id = "report-write-warning"
    assert _run_pipeline(pdf, vault, run_id).returncode == 0
    run_dir = vault / ".local" / "deeppapernote" / "runs" / run_id
    bundle = load_json_object(run_dir / "synthesis_bundle.json")
    emit_json(build_note_plan_artifact(_plan(bundle), bundle), run_dir / "note_plan.json")
    (run_dir / "staging" / "笔记.md").write_text(_note(), encoding="utf-8", newline="\n")
    (run_dir / "second_review.input.json").write_text(
        json.dumps(_review(bundle), ensure_ascii=False), encoding="utf-8"
    )
    report_path = run_dir / "publish_report.json"
    original_emit_json = publish_note_v2.emit_json

    def fail_only_final_report(payload: dict, output: Path | str | None = None) -> None:
        if output is not None and Path(output) == report_path:
            raise OSError("simulated final report write failure")
        original_emit_json(payload, output)

    monkeypatch.setattr(publish_note_v2, "emit_json", fail_only_final_report)
    with pytest.warns(RuntimeWarning, match="final report could not be written"):
        report = publish_note_v2.finalize_run(
            vault=vault,
            run_id=run_id,
            author="note-author",
            backup_root=vault / ".local" / "deeppapernote" / "rollback" / run_id,
            output=None,
        )

    assert report["target_lint_status"] == "pass"
    assert (paper_dir / "笔记.md").is_file()
    assert not report_path.exists()


def test_finalizer_rejects_image_markup(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Graphene quantum Hall transport experiment"
    paper_dir.mkdir(parents=True)
    pdf = _make_pdf(paper_dir / "paper.pdf")
    assert _run_pipeline(pdf, vault, "reject-images").returncode == 0
    run_dir = vault / ".local" / "deeppapernote" / "runs" / "reject-images"
    bundle = load_json_object(run_dir / "synthesis_bundle.json")
    emit_json(build_note_plan_artifact(_plan(bundle), bundle), run_dir / "note_plan.json")
    (run_dir / "staging" / "笔记.md").write_text(
        _note() + "\n![[images/not-allowed.png]]\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "second_review.input.json").write_text(
        json.dumps(_review(bundle), ensure_ascii=False), encoding="utf-8"
    )

    try:
        publish_note_v2.finalize_run(
            vault=vault,
            run_id="reject-images",
            author="note-author",
            backup_root=vault / ".local" / "deeppapernote" / "rollback" / "reject-images",
            output=None,
        )
    except Exception as exc:
        assert "Text-only notes must not embed images" in str(exc)
    else:
        raise AssertionError("Text-only finalizer accepted an image embed")


@pytest.mark.parametrize(
    "markup",
    [
        "![[images/not-allowed.png]]",
        "![inline](images/not-allowed.png)",
        "![reference][figure]\n[figure]: images/not-allowed.png",
        "![shortcut]\n[shortcut]: images/not-allowed.png",
        '<img src="images/not-allowed.png">',
    ],
)
def test_text_only_gate_recognizes_every_image_embed_form(markup: str) -> None:
    assert publish_note_v2._image_markup_present(markup)

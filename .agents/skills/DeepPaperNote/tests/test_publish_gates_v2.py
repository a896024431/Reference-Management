# ruff: noqa: E402

from __future__ import annotations

import base64
import sys
from pathlib import Path

import fitz
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_synthesis_bundle_v2 import build_bundle
from contracts_v2 import ContractError, artifact_header, sha256_file, sha256_text
from lint_note_v2 import build_release_lint
from publish_note_v2 import validate_note_image_set, validate_release, validate_synthesis_binding
from record_note_review_v2 import build_review_artifact
from validate_note_plan_v2 import build_note_plan_artifact


def context_bundle() -> tuple[dict, dict, dict]:
    record = artifact_header("paper_record", paper_id="doi:10.1000/test", run_id="run-test")
    record["paper_record"] = {
        "paper_id": record["paper_id"],
        "metadata": {
            "title": "Quantum Hall Test Paper",
            "abstract": "We measure conductance in a graphene device.",
        },
        "documents": [
            {
                "document_id": "doc:main",
                "role": "main",
                "path": "",
                "url": "https://example.test/paper.pdf",
                "source": "test",
                "sha256": "0" * 64,
                "pages": 3,
                "filename": "paper.pdf",
            }
        ],
    }
    evidence = artifact_header(
        "evidence_pack", paper_id=record["paper_id"], run_id=record["run_id"]
    )
    document = dict(record["paper_record"]["documents"][0])
    units = [
        {
            "evidence_id": "ev:1",
            "document_id": "doc:main",
            "document_role": "main",
            "page": 1,
            "section": "introduction",
            "types": ["problem"],
            "text": "problem",
        },
        {
            "evidence_id": "ev:2",
            "document_id": "doc:main",
            "document_role": "main",
            "page": 2,
            "section": "method",
            "types": ["protocol"],
            "text": "protocol",
        },
        {
            "evidence_id": "ev:3",
            "document_id": "doc:main",
            "document_role": "main",
            "page": 3,
            "section": "results",
            "types": ["results"],
            "text": "results",
        },
    ]
    evidence["evidence_pack"] = {
        "paper_id": record["paper_id"],
        "paper_type": "experimental_physics",
        "paper_type_rationale": "measurement signals",
        "evidence_quality": "high",
        "documents": [document],
        "coverage": {
            "required": ["problem", "protocol", "results"],
            "available": ["problem", "protocol", "results"],
            "missing": [],
            "ratio": 1.0,
            "text_pages": 3,
            "total_pages": 3,
            "needs_ocr": False,
        },
        "evidence_units": units,
        "page_records": [
            {
                "document_id": "doc:main",
                "document_role": "main",
                "page": page,
                "text_chars": 100,
            }
            for page in range(1, 4)
        ],
        "extraction_failures": [],
    }
    return record, evidence, build_bundle(record, evidence)


def local_context_bundle(tmp_path: Path) -> tuple[dict, dict, dict]:
    record, evidence, _ = context_bundle()
    source_dir = tmp_path.parent / f"{tmp_path.name}-source"
    source_dir.mkdir()
    pdf_path = source_dir / "paper.pdf"
    pdf = fitz.open()
    try:
        for page_number in range(1, 4):
            page = pdf.new_page()
            page.insert_text((72, 72), f"Evidence page {page_number}")
        pdf.save(pdf_path)
    finally:
        pdf.close()
    document = record["paper_record"]["documents"][0]
    document.update({"path": str(pdf_path), "url": "", "sha256": sha256_file(pdf_path)})
    evidence["evidence_pack"]["documents"][0] = dict(document)
    return record, evidence, build_bundle(record, evidence)


def test_synthesis_binding_rejects_modified_section_texts() -> None:
    record, evidence, _ = context_bundle()
    manifest = artifact_header(
        "figure_manifest", paper_id=record["paper_id"], run_id=record["run_id"]
    )
    manifest["assets"] = []
    decisions = artifact_header(
        "figure_decisions",
        paper_id=record["paper_id"],
        run_id=record["run_id"],
        status="degraded",
    )
    decisions["decisions"] = []
    context = build_bundle(record, evidence, decisions, manifest)
    assert validate_synthesis_binding(record, evidence, context, manifest) == (
        "experimental_physics"
    )
    context["section_texts"] = {"results": "fabricated text"}

    with pytest.raises(ContractError, match=r"synthesis_bundle\.section_texts"):
        validate_synthesis_binding(record, evidence, context, manifest)


def note_text() -> str:
    return """---
type: paper
title: Quantum Hall Test Paper
title_zh: 量子霍尔测试论文
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
figure_status: placeholder_only
aliases:
  - QH Test
  - 量子霍尔测试
tags:
  - papers/physics/condensed-matter
---

# 量子霍尔测试论文

## 30 秒速览
这项工作研究低温边缘输运。

## 关键结论
- 第一项结论有数据支持〔主文 p. 1〕。
- 第二项结论说明控制有效〔主文 p. 2〕。
- 第三项结论限定解释范围〔主文 p. 3〕。

## 关键数字
- 测量温度为二十毫开尔文〔主文 p. 2〕。

## 适用边界
结论只适用于论文给出的器件和测量区间。

## 快速入口与页面导航
- [[#研究问题|进入研究问题]]

## 原文摘要翻译
> [!abstract]- 展开查看中文摘要
> 作者研究了石墨烯量子霍尔器件中的电导行为。

## 创新点
论文把可调器件控制与输运证据结合起来。

## 研究问题
研究问题是边缘输运如何随器件控制改变。

## 实验体系、方法或理论模型
作者制备器件并在低温条件下测量电导。

文中 Fig. 1 给出器件与测量示意；即使不嵌入图片，正文的证据链仍可独立阅读。


## 主要结果与证据链
测量给出了随控制参数变化的可重复趋势。

## 解释、替代解释与证据边界
结果支持边缘态解释，但未排除器件非均匀性的影响。

## 局限与未决问题
样品数量和参数范围限制了外推。

## 可复用结论
后续实验应同时记录器件几何和控制参数。

## 相关论文
暂无已确认的库内关联笔记。

## 我的笔记
值得比较不同器件几何下的稳定性。

## 引用
- Researcher 等，量子霍尔测试论文，二〇二五年。
"""


def quality_source() -> dict:
    return {
        "reviewer": "independent-quality-reviewer",
        "review_origin": "subagent",
        "independent": True,
        "scores": {
            "factual_fidelity": 4,
            "completeness": 4,
            "domain_expression": 4,
            "clarity": 4,
            "traceability": 4,
        },
        "unresolved_issues": [],
        "claims_checked": [
            {"claim": "one", "evidence_ids": ["ev:1"]},
            {"claim": "two", "evidence_ids": ["ev:2"]},
            {"claim": "three", "evidence_ids": ["ev:3"]},
        ],
    }


def readability_source() -> dict:
    return {
        "reviewer": "independent-language-reviewer",
        "review_origin": "subagent",
        "independent": True,
        "scores": {
            "factual_fidelity": 4,
            "completeness": 4,
            "domain_expression": 4,
            "chinese_naturalness": 4,
            "navigability": 4,
        },
        "unresolved_issues": [],
    }


def test_hash_bound_lint_quality_and_readability_gates() -> None:
    _, _, context = context_bundle()
    note = note_text()
    lint = build_release_lint(note, context)
    assert lint["status"] == "pass", lint["failures"]
    quality = build_review_artifact(
        kind="quality",
        author="note-author",
        note_text=note,
        review_source=quality_source(),
        context=context
    )
    readability = build_review_artifact(
        kind="readability",
        author="note-author",
        note_text=note,
        review_source=readability_source(),
        context=context,
        lint=lint,
    )
    assert quality["note_sha256"] == lint["note_sha256"] == readability["note_sha256"]
    try:
        build_review_artifact(
            kind="readability",
            author="note-author",
            note_text=note + "\n改动。",
            review_source=readability_source(),
            context=context,
            lint=lint,
        )
    except ContractError:
        pass
    else:
        raise AssertionError("readability accepted a note changed after lint")


def test_strict_release_accepts_explicit_final_placeholder(tmp_path: Path) -> None:
    record, evidence, context = local_context_bundle(tmp_path)
    note = note_text()
    lint = build_release_lint(note, context)
    plan = build_note_plan_artifact(
        {
            "paper_type": "experimental_physics",
            "dominant_domain": "condensed-matter-physics",
            "evidence_ids": ["ev:1", "ev:2", "ev:3"],
            "must_cover": [
                {"topic": "experiment", "evidence_ids": ["ev:1", "ev:2"]},
                {"topic": "results", "evidence_ids": ["ev:3"]},
            ],
            "key_claims": [
                {"claim": "problem", "evidence_ids": ["ev:1"]},
                {"claim": "protocol", "evidence_ids": ["ev:2"]},
                {"claim": "result", "evidence_ids": ["ev:3"]},
            ],
            "key_numbers": [{"number": "20 mK", "evidence_ids": ["ev:2"]}],
            "real_comparisons": [
                {
                    "comparison": "controlled settings",
                    "evidence_ids": ["ev:2", "ev:3"],
                }
            ],
            "section_plan": [
                {
                    "section": "主要结果与证据链",
                    "evidence_ids": ["ev:1", "ev:2", "ev:3"],
                }
            ],
            "figure_intents": [],
        },
        context,
    )
    quality = build_review_artifact(
        kind="quality",
        author="note-author",
        note_text=note,
        review_source=quality_source(),
        context=context
    )
    readability = build_review_artifact(
        kind="readability",
        author="note-author",
        note_text=note,
        review_source=readability_source(),
        context=context,
        lint=lint,
    )
    manifest = artifact_header(
        "figure_manifest", paper_id=context["paper_id"], run_id=context["run_id"]
    )
    manifest["assets"] = []
    decisions = artifact_header(
        "figure_decisions", paper_id=context["paper_id"], run_id=context["run_id"]
    )
    decisions["decisions"] = [
        {
            "target_id": "Fig. 1",
            "decision": "placeholder",
            "selected_asset_id": "",
            "candidate_asset_ids": [],
            "rejected_asset_ids": [],
            "decision_reason": "No complete, visually usable crop is available.",
        }
    ]
    (tmp_path / "images").mkdir()
    (tmp_path / "笔记.md").write_text(note, encoding="utf-8")
    release = validate_release(
        staging_dir=tmp_path,
        artifacts={
            "paper_record": record,
            "evidence_pack": evidence,
            "synthesis_bundle": context,
            "note_plan": plan,
            "lint_report": lint,
            "quality_review": quality,
            "readability_review": readability,
            "figure_manifest": manifest,
            "figure_decisions": decisions,
        },
    )
    assert release["note_sha256"] == lint["note_sha256"]

    plan["note_plan"]["paper_type"] = "generic"
    with pytest.raises(ContractError, match="note_plan.paper_type must match"):
        validate_release(
            staging_dir=tmp_path,
            artifacts={
                "paper_record": record,
                "evidence_pack": evidence,
                "synthesis_bundle": context,
                "note_plan": plan,
                "lint_report": lint,
                "quality_review": quality,
                "readability_review": readability,
                "figure_manifest": manifest,
                "figure_decisions": decisions,
            },
        )
    plan["note_plan"]["paper_type"] = "experimental_physics"

    plan["note_plan"]["figure_intents"] = [
        {"target_id": "Fig. 2", "evidence_ids": ["ev:3"]}
    ]
    with pytest.raises(ContractError, match="lack final decisions"):
        validate_release(
            staging_dir=tmp_path,
            artifacts={
                "paper_record": record,
                "evidence_pack": evidence,
                "synthesis_bundle": context,
                "note_plan": plan,
                "lint_report": lint,
                "quality_review": quality,
                "readability_review": readability,
                "figure_manifest": manifest,
                "figure_decisions": decisions,
            },
        )


def test_local_image_references_and_files_must_match_exactly(tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    note = "![[images/fig-1.png]]\n"

    with pytest.raises(ContractError, match="image_missing:fig-1.png"):
        validate_note_image_set(note, image_dir, label="Test")

    image_dir.joinpath("fig-1.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    assert validate_note_image_set(note, image_dir, label="Test") == {"fig-1.png"}

    with pytest.raises(ContractError, match="image_reference_unsafe"):
        validate_note_image_set("![[../images/fig-1.png]]\n", image_dir, label="Test")

    with pytest.raises(ContractError, match="external_image_forbidden"):
        validate_note_image_set(
            "![remote](https://example.org/unreviewed.png)\n",
            tmp_path / "empty-images",
            label="Test",
        )

    with pytest.raises(ContractError, match="html_image_embed_forbidden"):
        validate_note_image_set(
            '<img src="images/fig-1.png">\n',
            image_dir,
            label="Test",
        )


def test_release_lint_rejects_reader_visible_figure_metadata() -> None:
    _, _, context = context_bundle()
    note = (
        note_text()
        + """
> [!figure] Fig. 2 器件图
> 建议位置：实验设计与分析方法
> 放置原因：便于理解器件。
> 当前状态：已插入；已通过图号身份、面板完整性与哈希一致性复核。
<!-- figure-target: doc:main|fig-2 -->
doc:main|fig-2
该 candidate crop 已进入 contact sheet QA gate，并被 materialize。
"""
    )

    lint = build_release_lint(note, context)

    expected = {
        "published_html_comment_present",
        "figure_placeholder_callout_present",
        "figure_planning_label_present",
        "source_figure_target_id_present",
        "figure_qa_metadata_present",
        "figure_process_metadata_present",
    }
    assert lint["status"] == "fail"
    assert expected.issubset(set(lint["failures"]))
    assert not lint["passes_publication_hygiene_gate"]


def test_release_lint_accepts_reader_facing_section_aliases() -> None:
    _, _, context = context_bundle()
    note = note_text()
    note = note.replace("## 实验体系、方法或理论模型", "## 实验设计与分析方法")
    note = note.replace("## 主要结果与证据链", "## 主要结果")
    note = note.replace("## 解释、替代解释与证据边界", "## 如何理解这些结果")

    lint = build_release_lint(note, context)

    assert lint["status"] == "pass", lint["failures"]


def test_publish_guard_rejects_metadata_even_if_lint_artifact_claims_pass(tmp_path: Path) -> None:
    record, evidence, context = local_context_bundle(tmp_path)
    note = note_text() + "\n<!-- figure-target: doc:main|fig-1 -->\n"
    lint = build_release_lint(note_text(), context)
    lint["note_sha256"] = sha256_text(note)
    quality = build_review_artifact(
        kind="quality",
        author="note-author",
        note_text=note,
        review_source=quality_source(),
        context=context
    )
    readability = build_review_artifact(
        kind="readability",
        author="note-author",
        note_text=note,
        review_source=readability_source(),
        context=context,
        lint=lint,
    )
    plan = build_note_plan_artifact(
        {
            "paper_type": "experimental_physics",
            "dominant_domain": "condensed-matter-physics",
            "evidence_ids": ["ev:1", "ev:2", "ev:3"],
            "must_cover": [
                {"topic": "experiment", "evidence_ids": ["ev:1", "ev:2"]},
                {"topic": "results", "evidence_ids": ["ev:3"]},
            ],
            "key_claims": [
                {"claim": "problem", "evidence_ids": ["ev:1"]},
                {"claim": "protocol", "evidence_ids": ["ev:2"]},
                {"claim": "result", "evidence_ids": ["ev:3"]},
            ],
            "key_numbers": [{"number": "20 mK", "evidence_ids": ["ev:2"]}],
            "real_comparisons": [
                {
                    "comparison": "controlled settings",
                    "evidence_ids": ["ev:2", "ev:3"],
                }
            ],
            "section_plan": [
                {
                    "section": "主要结果与证据链",
                    "evidence_ids": ["ev:1", "ev:2", "ev:3"],
                }
            ],
            "figure_intents": [],
        },
        context,
    )
    manifest = artifact_header(
        "figure_manifest", paper_id=context["paper_id"], run_id=context["run_id"]
    )
    manifest["assets"] = []
    decisions = artifact_header(
        "figure_decisions", paper_id=context["paper_id"], run_id=context["run_id"]
    )
    decisions["decisions"] = [
        {
            "target_id": "Fig. 1",
            "decision": "placeholder",
            "selected_asset_id": "",
            "candidate_asset_ids": [],
            "rejected_asset_ids": [],
            "decision_reason": "No complete, visually usable crop is available.",
        }
    ]
    (tmp_path / "images").mkdir()
    (tmp_path / "笔记.md").write_text(note, encoding="utf-8")

    with pytest.raises(ContractError, match="Reader-visible figure metadata"):
        validate_release(
            staging_dir=tmp_path,
            artifacts={
                "paper_record": record,
                "evidence_pack": evidence,
                "synthesis_bundle": context,
                "note_plan": plan,
                "lint_report": lint,
                "quality_review": quality,
                "readability_review": readability,
                "figure_manifest": manifest,
                "figure_decisions": decisions,
            },
        )

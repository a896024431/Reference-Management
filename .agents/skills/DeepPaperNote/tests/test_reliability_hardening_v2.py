from __future__ import annotations

import argparse
from pathlib import Path

import fitz
import paper_record_v2
import pytest
import run_pipeline_v2
from common import title_resolution
from contracts_v2 import ContractError, artifact_header, sha256_file
from create_paper_record_v2 import create_explicit_record
from extract_evidence_v2 import build_contract_evidence
from lint_note_v2 import build_release_lint
from paper_record_v2 import fetch_stage, resolve_stage
from publish_note_v2 import (
    expected_evidence_level,
    expected_figure_status,
    validate_staging_contents,
)
from record_note_review_v2 import build_review_artifact
from test_publish_gates_v2 import context_bundle, note_text
from validate_note_plan_v2 import build_note_plan_artifact


def _make_pdf(path: Path, pages: list[str], *, title: str = "Test Paper") -> Path:
    document = fitz.open()
    try:
        document.set_metadata({"title": title})
        for text in pages:
            page = document.new_page()
            page.insert_textbox(
                fitz.Rect(48, 48, 548, 760),
                text,
                fontsize=10,
            )
        document.save(str(path))
    finally:
        document.close()
    return path


def _evidence_pages() -> list[str]:
    return [
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
            "We observe that conductance increases by 10 percent under the controlled "
            "setting in Fig. 2. The repeated measurement supports the reported result "
            "while device inhomogeneity remains a limitation."
        ),
    ]


def _context() -> dict:
    _, _, context = context_bundle()
    return context


def _canonical_plan() -> dict:
    return {
        "paper_type": "experimental_physics",
        "dominant_domain": "condensed-matter-physics",
        "evidence_ids": ["ev:1", "ev:2", "ev:3"],
        "must_cover": [
            {"topic": "problem", "evidence_ids": ["ev:1"]},
            {"topic": "method", "evidence_ids": ["ev:2"]},
            {"topic": "result", "evidence_ids": ["ev:3"]},
        ],
        "key_claims": [
            {"claim": "claim one", "evidence_ids": ["ev:1"]},
            {"claim": "claim two", "evidence_ids": ["ev:2"]},
            {"claim": "claim three", "evidence_ids": ["ev:3"]},
        ],
        "key_numbers": [{"number": "20 mK", "evidence_ids": ["ev:2"]}],
        "real_comparisons": [
            {"comparison": "controlled settings", "evidence_ids": ["ev:2", "ev:3"]}
        ],
        "section_plan": [
            {
                "section": "主要结果与证据链",
                "evidence_ids": ["ev:1", "ev:2", "ev:3"],
            }
        ],
        "figure_intents": [],
    }


def _quality_review(*, reviewer: str, origin: str = "subagent") -> dict:
    return {
        "reviewer": reviewer,
        "review_origin": origin,
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


def test_title_resolution_deduplicates_provider_records_for_one_work() -> None:
    query = "A Shared Quantum Transport Result"
    resolution = title_resolution(
        query,
        [
            {
                "title": query,
                "year": "2025",
                "doi": "10.1000/shared",
                "source": "crossref",
            },
            {
                "title": query,
                "year": "2025",
                "doi": "10.1000/shared",
                "source": "openalex",
            },
        ],
    )

    assert resolution["status"] == "ok"
    assert resolution["record"]["doi"] == "10.1000/shared"


def test_title_resolution_fails_when_multiple_credible_identities_remain() -> None:
    query = "A Shared Quantum Transport Result"
    resolution = title_resolution(
        query,
        [
            {"title": query, "year": "2024", "doi": "10.1000/first"},
            {"title": query, "year": "2025", "doi": "10.1000/second"},
        ],
    )

    assert resolution["status"] == "ambiguous"
    assert {item["doi"] for item in resolution["candidates"]} == {
        "10.1000/first",
        "10.1000/second",
    }


def test_resolve_stage_turns_ambiguous_title_into_failed_artifact(monkeypatch) -> None:
    monkeypatch.setattr(
        paper_record_v2,
        "resolve_reference",
        lambda value: {
            "status": "ambiguous",
            "source_type": "title_query",
            "title": value,
            "resolution_candidates": [{"title": value, "doi": "10.1000/a"}],
        },
    )

    artifact = resolve_stage("Ambiguous Study", run_id="run-ambiguity")

    assert artifact["status"] == "fail"
    assert artifact["failures"] == ["paper_identity_ambiguous"]


def test_raw_local_fetch_records_only_safe_vault_relative_path(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "paper.pdf",
        _evidence_pages(),
        title="Graphene quantum Hall transport experiment",
    )
    resolved = resolve_stage(str(pdf), run_id="run-vault")

    fetched = fetch_stage(
        resolved,
        supplements=[],
        dest_dir=str(tmp_path / "downloads"),
        vault_root=str(tmp_path),
    )

    assert fetched["status"] == "pass"
    document = fetched["paper_record"]["documents"][0]
    assert document["vault_path"] == "paper.pdf"
    assert Path(document["path"]).is_absolute()


def test_full_text_truncation_is_a_hard_failure(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "paper.pdf", _evidence_pages())
    record = create_explicit_record(
        {
            "title": "Graphene quantum Hall transport experiment",
            "main_pdf": str(pdf),
        },
        run_id="run-truncated",
        vault_root=str(tmp_path),
    )

    evidence = build_contract_evidence(record, max_pages=2)

    assert evidence["status"] == "fail"
    assert any(failure.startswith("document_truncated:") for failure in evidence["failures"])


def test_scanned_or_blank_pdf_requires_ocr_and_fails(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "blank.pdf", ["", "", ""])
    record = create_explicit_record(
        {"title": "Blank scanned study", "main_pdf": str(pdf)},
        run_id="run-ocr",
    )

    evidence = build_contract_evidence(record)

    assert evidence["status"] == "fail"
    assert any(failure.startswith("needs_ocr:") for failure in evidence["failures"])


def test_document_parse_failure_is_not_degraded(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a PDF")
    record = artifact_header(
        "paper_record",
        paper_id="paper:corrupt",
        run_id="run-corrupt",
    )
    record["paper_record"] = {
        "paper_id": record["paper_id"],
        "metadata": {"title": "Corrupt document"},
        "documents": [
            {
                "document_id": "doc:main",
                "role": "main",
                "path": str(corrupt),
                "url": "",
                "source": "test",
                "sha256": sha256_file(corrupt),
                "pages": 1,
                "filename": corrupt.name,
            }
        ],
    }

    evidence = build_contract_evidence(record)

    assert evidence["status"] == "fail"
    assert any(failure.startswith("document_parse_failed:") for failure in evidence["failures"])


def test_environment_gate_runs_before_any_run_directory(monkeypatch, tmp_path: Path) -> None:
    args = argparse.Namespace(max_pages=0, vault_root="")
    monkeypatch.setattr(run_pipeline_v2.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(SystemExit, match="PyMuPDF"):
        run_pipeline_v2.validate_environment(args)

    assert list(tmp_path.iterdir()) == []


def test_note_plan_requires_nested_evidence_bindings() -> None:
    plan = _canonical_plan()
    del plan["key_claims"][0]["evidence_ids"]

    with pytest.raises(ContractError, match=r"key_claims\[0\]\.evidence_ids"):
        build_note_plan_artifact(plan, _context())


def test_note_plan_rejects_unknown_nested_evidence_id() -> None:
    plan = _canonical_plan()
    plan["key_claims"][0]["evidence_ids"] = ["ev:unknown"]
    plan["evidence_ids"] = ["ev:unknown", "ev:2", "ev:3"]
    plan["must_cover"][0]["evidence_ids"] = ["ev:unknown"]
    plan["section_plan"][0]["evidence_ids"] = ["ev:unknown", "ev:2", "ev:3"]

    with pytest.raises(ContractError, match="unknown evidence ids"):
        build_note_plan_artifact(plan, _context())


def test_note_plan_rejects_unused_top_level_evidence_id() -> None:
    plan = _canonical_plan()
    plan["evidence_ids"].append("ev:unused")

    with pytest.raises(ContractError, match="evidence index mismatch"):
        build_note_plan_artifact(plan, _context())


def test_note_plan_rejects_unexpected_top_level_fields() -> None:
    plan = _canonical_plan()
    plan["formulas"] = []

    with pytest.raises(ContractError, match="unexpected fields: formulas"):
        build_note_plan_artifact(plan, _context())


def test_note_plan_rejects_unexpected_entry_fields() -> None:
    plan = _canonical_plan()
    plan["must_cover"][0]["weight"] = "high"

    with pytest.raises(ContractError, match=r"must_cover\[0\] has unexpected fields: weight"):
        build_note_plan_artifact(plan, _context())


def test_independent_review_records_author_reviewer_and_origin() -> None:
    artifact = build_review_artifact(
        kind="quality",
        author="note-author",
        note_text=note_text(),
        review_source=_quality_review(reviewer="review-subagent"),
        context=_context(),
    )

    assert artifact["status"] == "pass"
    assert artifact["author"] == "note-author"
    assert artifact["reviewer"] == "review-subagent"
    assert artifact["review_origin"] == "subagent"


def test_self_review_and_untrusted_review_origin_fail() -> None:
    self_review = build_review_artifact(
        kind="quality",
        author="same-agent",
        note_text=note_text(),
        review_source=_quality_review(reviewer="same-agent"),
        context=_context(),
    )
    bad_origin = build_review_artifact(
        kind="quality",
        author="note-author",
        note_text=note_text(),
        review_source=_quality_review(reviewer="reviewer", origin="self-asserted"),
        context=_context(),
    )

    assert self_review["status"] == "fail"
    assert "reviewer_matches_author" in self_review["failures"]
    assert bad_origin["status"] == "fail"
    assert "review_origin_invalid" in bad_origin["failures"]


def test_lint_rejects_duplicate_english_title_and_multiple_h1() -> None:
    note = note_text().replace(
        "# 量子霍尔测试论文",
        (
            "# 量子霍尔测试论文\n\n"
            "*Quantum Hall Test Paper*\n\n"
            "*Quantum Hall Test Paper*\n\n"
            "# Duplicate Heading"
        ),
    )

    lint = build_release_lint(note, _context())

    assert "duplicate_english_title" in lint["failures"]
    assert "multiple_h1_headings" in lint["failures"]


def test_lint_requires_an_anchor_on_each_key_claim() -> None:
    note = note_text().replace(
        "- 第一项结论有数据支持〔主文 p. 1〕。",
        "- 第一项结论有数据支持。",
    )

    lint = build_release_lint(note, _context())

    assert "key_claim_missing_source_anchor:1" in lint["failures"]
    assert not lint["passes_traceability_gate"]


def test_lint_rejects_broken_internal_heading_links() -> None:
    note = note_text().replace(
        "## 快速入口与页面导航",
        "## 快速入口与页面导航\n\n[[#不存在的章节|坏链接]]",
    )

    lint = build_release_lint(note, _context())

    assert "internal_heading_link_missing:不存在的章节" in lint["failures"]
    assert [item["target"] for item in lint["broken_internal_heading_links"]] == ["不存在的章节"]
    assert lint["broken_internal_heading_links"][0]["line"] > 0
    assert not lint["passes_basic_structure"]


def test_lint_rejects_latex_command_outside_math_but_accepts_inline_math() -> None:
    command = chr(92) + "nu=-1"
    raw = note_text().replace(
        "这项工作研究低温边缘输运。",
        "这项工作研究低温边缘输运，并讨论 " + command + "。",
    )
    fixed = raw.replace(command, "$" + command + "$")

    raw_lint = build_release_lint(raw, _context())
    fixed_lint = build_release_lint(fixed, _context())

    assert "latex_command_outside_math" in raw_lint["failures"]
    assert "latex_command_outside_math" not in fixed_lint["failures"]


def test_publisher_derives_evidence_and_figure_statuses() -> None:
    record, _, _ = context_bundle()
    assert expected_evidence_level(record) == "full_text"
    record["paper_record"]["documents"].append(
        {
            "document_id": "doc:supplement",
            "role": "supplement",
            "path": "",
            "url": "https://example.test/supplement.pdf",
            "source": "test",
            "sha256": "1" * 64,
            "pages": 2,
            "filename": "supplement.pdf",
        }
    )
    assert expected_evidence_level(record) == "full_text_supplement"

    assert expected_figure_status({"decisions": []}) == "none_needed"
    assert (
        expected_figure_status({"decisions": [{"decision": "placeholder"}]}) == "placeholder_only"
    )
    assert (
        expected_figure_status(
            {"decisions": [{"decision": "placeholder"}, {"decision": "inserted"}]}
        )
        == "partial"
    )
    assert (
        expected_figure_status({"decisions": [{"decision": "inserted"}, {"decision": "omitted"}]})
        == "complete"
    )


def test_staging_contract_rejects_extra_and_non_image_files(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "笔记.md").write_text(note_text(), encoding="utf-8")
    (tmp_path / "unexpected.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ContractError, match="extra=unexpected.json"):
        validate_staging_contents(tmp_path)

    (tmp_path / "unexpected.json").unlink()
    (tmp_path / "images" / "metadata.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="non-image assets"):
        validate_staging_contents(tmp_path)

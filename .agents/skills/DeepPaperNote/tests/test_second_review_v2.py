from __future__ import annotations

import pytest
from contracts_v2 import ContractError, artifact_header
from record_second_review_v2 import build_second_review_artifact


def _context() -> dict:
    context = artifact_header("synthesis_bundle", paper_id="doi:10.1000/test", run_id="review-run")
    context.update(
        {
            "paper_type": "experimental_physics",
            "evidence_units": [
                {
                    "evidence_id": "ev:1",
                    "document_id": "doc:main",
                    "document_role": "main",
                    "page": 1,
                    "section": "results",
                    "types": ["results"],
                    "text": "evidence one",
                },
                {
                    "evidence_id": "ev:2",
                    "document_id": "doc:main",
                    "document_role": "main",
                    "page": 2,
                    "section": "results",
                    "types": ["results"],
                    "text": "evidence two",
                },
                {
                    "evidence_id": "ev:3",
                    "document_id": "doc:main",
                    "document_role": "main",
                    "page": 3,
                    "section": "results",
                    "types": ["results"],
                    "text": "evidence three",
                },
            ],
        }
    )
    return context


def _review() -> dict:
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
            {"heading": "结论", "quote": "第一条结论", "evidence_ids": ["ev:1"]},
            {"heading": "结论", "quote": "第二条结论", "evidence_ids": ["ev:2"]},
            {"heading": "结论", "quote": "第三条结论", "evidence_ids": ["ev:3"]},
        ],
    }


def test_second_review_binds_real_note_passages_and_evidence() -> None:
    note = "## 结论\n第一条结论\n\n第二条结论\n\n第三条结论\n"
    artifact = build_second_review_artifact(
        author="note-author",
        note_text=note,
        review_source=_review(),
        context=_context(),
    )

    assert artifact["status"] == "pass"
    assert artifact["artifact_type"] == "second_review"
    assert "independent" not in artifact["review"]


def test_second_review_rejects_a_quote_not_in_the_note() -> None:
    review = _review()
    review["passages_checked"][1]["quote"] = "不存在的文字"
    note = "## 结论\n第一条结论\n\n第二条结论\n\n第三条结论\n"

    with pytest.raises(ContractError, match="declared Markdown heading"):
        build_second_review_artifact(
            author="note-author",
            note_text=note,
            review_source=review,
            context=_context(),
        )


def test_second_review_rejects_quote_under_the_wrong_heading() -> None:
    review = _review()
    review["passages_checked"][0]["heading"] = "其他部分"
    note = "## 结论\n第一条结论\n\n第二条结论\n\n第三条结论\n\n## 其他部分\n无关文字。\n"

    with pytest.raises(ContractError, match="declared Markdown heading"):
        build_second_review_artifact(
            author="note-author",
            note_text=note,
            review_source=review,
            context=_context(),
        )


def test_second_review_requires_three_different_paragraphs() -> None:
    note = "## 结论\n第一条结论；第二条结论；第三条结论。\n"

    with pytest.raises(ContractError, match="different note paragraphs"):
        build_second_review_artifact(
            author="note-author",
            note_text=note,
            review_source=_review(),
            context=_context(),
        )

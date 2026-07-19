# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_synthesis_bundle_v2 import build_bundle
from contracts_v2 import (
    ContractError,
    artifact_header,
    require_same_identity,
    require_v2_artifact,
    sha256_file,
    validate_evidence_pack_artifact,
)
from extract_evidence_v2 import build_evidence_artifact, infer_paper_type_v2, match_heading_v2


def make_record(pdf: Path | None = None) -> dict:
    artifact = artifact_header("paper_record", paper_id="doi:10.1000/test", run_id="run-test")
    documents = []
    if pdf is not None:
        documents.append(
            {
                "document_id": "doc:main",
                "role": "main",
                "path": str(pdf),
                "url": "",
                "source": "test",
                "sha256": sha256_file(pdf),
                "pages": 3,
                "filename": pdf.name,
            }
        )
    artifact["paper_record"] = {
        "paper_id": artifact["paper_id"],
        "metadata": {
            "title": "Graphene quantum Hall transport experiment",
            "abstract": "We measure conductance in a low-temperature device.",
        },
        "documents": documents,
    }
    return artifact


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_text(self, mode: str) -> str:
        assert mode == "text"
        return self.text


class FakeDocument:
    def __init__(self, pages: list[str]) -> None:
        self.pages = [FakePage(text) for text in pages]

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> FakePage:
        return self.pages[index]

    def close(self) -> None:
        return None


class FakeFitz:
    def __init__(self, pages: list[str]) -> None:
        self.pages = pages

    def open(self, path: Path) -> FakeDocument:
        return FakeDocument(self.pages)


def test_legacy_contract_and_identity_mismatch_fail_closed() -> None:
    try:
        require_v2_artifact({"paper_id": "paper:x", "status": "ok"})
    except ContractError:
        pass
    else:
        raise AssertionError("legacy artifact was accepted")
    first = artifact_header("a", paper_id="paper:a", run_id="run")
    second = artifact_header("b", paper_id="paper:b", run_id="run")
    try:
        require_same_identity(first, second)
    except ContractError:
        pass
    else:
        raise AssertionError("identity mismatch was accepted")


def test_pass_artifacts_cannot_carry_failures() -> None:
    with pytest.raises(ContractError, match="Passing artifacts"):
        artifact_header(
            "test_artifact",
            paper_id="paper:test",
            run_id="run-test",
            status="pass",
            failures=["hidden_failure"],
        )

    artifact = artifact_header("test_artifact", paper_id="paper:test", run_id="run-test")
    artifact["failures"] = ["tampered_failure"]
    with pytest.raises(ContractError, match="Passing artifacts"):
        require_v2_artifact(artifact)


def test_profiles_do_not_default_physics_or_generic_work_to_ai() -> None:
    assert (
        infer_paper_type_v2(
            "Universal transport in a graphene quantum Hall point contact",
            "We measure conductance in a low-temperature device.",
        )[0]
        == "experimental_physics"
    )
    assert (
        infer_paper_type_v2(
            "Nanoscale patterning by local anodic oxidation",
            "We fabricate graphite gates by lithography.",
        )[0]
        == "materials_fabrication"
    )
    assert infer_paper_type_v2("An Unclassified Study", "General analysis.")[0] == "generic"


def test_section_parser_supports_roman_and_multiword_headings() -> None:
    assert match_heading_v2("II. MATERIALS AND METHODS") == "method"
    assert match_heading_v2("III Results and Discussion") == "results"
    assert match_heading_v2("IV. DEVICE FABRICATION") == "method"


def test_full_page_evidence_has_real_page_anchors_and_profile_coverage(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"placeholder")
    pages = [
        "I. INTRODUCTION\nWe investigate an open question in graphene quantum Hall transport.",
        "II. EXPERIMENTAL METHODS\nWe fabricate a device and measure conductance at 20 mK.",
        "III. RESULTS AND DISCUSSION\nWe observe conductance increases by 10 percent in Fig. 2.",
    ]
    record = make_record(pdf)
    with patch("extract_evidence_v2.fitz", FakeFitz(pages)):
        artifact = build_evidence_artifact(record)
    assert artifact["status"] == "pass", artifact["failures"]
    pack = artifact["evidence_pack"]
    assert len(pack["page_records"]) == 3
    assert pack["coverage"]["missing"] == []
    types_by_page = {unit["page"]: set(unit["types"]) for unit in pack["evidence_units"]}
    assert "problem" in types_by_page[1]
    assert "protocol" in types_by_page[2]
    assert "results" in types_by_page[3]
    assert all(
        field not in pack
        for field in (
            "problem_evidence",
            "task_evidence",
            "data_evidence",
            "method_evidence",
            "mechanism_evidence",
            "results_evidence",
            "ablation_evidence",
            "limitations_evidence",
            "quotes",
        )
    )
    validate_evidence_pack_artifact(
        artifact,
        paper_record_artifact=record,
    )


def test_evidence_extraction_rejects_a_replaced_same_page_count_file(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"original")
    record = make_record(pdf)
    pdf.write_bytes(b"replacement-with-the-same-declared-page-count")

    artifact = build_evidence_artifact(record)

    assert artifact["status"] == "fail"
    assert any(
        failure.startswith("document_sha256_mismatch:doc:main:")
        for failure in artifact["failures"]
    )


def test_evidence_extraction_rejects_a_file_changed_during_read(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"original")
    record = make_record(pdf)
    pages = [
        {
            "page": index,
            "text": text,
            "text_chars": len(text),
        }
        for index, text in enumerate(
            (
                "I. INTRODUCTION " + "problem " * 20,
                "II. METHODS " + "we measure " * 20,
                "III. RESULTS " + "we observe " * 20,
            ),
            start=1,
        )
    ]

    def mutating_read(path: Path, *, max_pages: int = 0) -> tuple[list[dict], int]:
        assert max_pages == 0
        path.write_bytes(b"changed-during-extraction")
        return pages, 3

    with patch("extract_evidence_v2.read_pages", side_effect=mutating_read):
        artifact = build_evidence_artifact(record)

    assert artifact["status"] == "fail"
    assert any(
        failure.startswith("document_changed_during_extraction:doc:main:")
        for failure in artifact["failures"]
    )


def test_bundle_does_not_truncate_evidence_or_long_sections() -> None:
    record = make_record()
    source_document = {
        "document_id": "doc:main",
        "role": "main",
        "url": "https://example.org/paper.pdf",
        "sha256": "0" * 64,
        "pages": 1,
    }
    record["paper_record"]["documents"] = [source_document]
    evidence = artifact_header(
        "evidence_pack", paper_id=record["paper_id"], run_id=record["run_id"]
    )
    evidence["evidence_pack"] = {
        "paper_id": record["paper_id"],
        "paper_type": "experimental_physics",
        "evidence_quality": "high",
        "documents": [source_document],
        "extraction_failures": [],
        "page_records": [
            {
                "document_id": "doc:main",
                "document_role": "main",
                "page": 1,
                "text_chars": 6000,
            }
        ],
        "coverage": {
            "required": ["problem", "protocol", "results"],
            "available": ["problem", "protocol", "results"],
            "missing": [],
            "ratio": 1.0,
            "total_pages": 1,
            "text_pages": 1,
            "needs_ocr": False,
        },
        "evidence_units": [
            {
                "evidence_id": f"ev:{index}",
                "document_id": "doc:main",
                "document_role": "main",
                "page": 1,
                "section": "results",
                "types": [
                    "problem" if index == 0 else "protocol" if index == 1 else "results"
                ],
                "text": f"result {index}",
            }
            for index in range(25)
        ],
        "section_texts": {"doc:main:results": "x" * 6000},
    }
    bundle = build_bundle(record, evidence)
    assert len(bundle["evidence_units"]) == 25
    assert len(bundle["section_texts"]["doc:main:results"]) == 6000

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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
    with patch("extract_evidence_v2.fitz", FakeFitz(pages)):
        artifact = build_evidence_artifact(make_record(pdf))
    assert artifact["status"] == "pass", artifact["failures"]
    pack = artifact["evidence_pack"]
    assert len(pack["page_records"]) == 3
    assert pack["coverage"]["missing"] == []
    assert pack["problem_evidence"] and pack["method_evidence"] and pack["results_evidence"]
    assert "主文 p. 3" in pack["results_evidence"][0]["page_hint"]


def test_bundle_does_not_truncate_evidence_or_long_sections() -> None:
    record = make_record()
    evidence = artifact_header(
        "evidence_pack", paper_id=record["paper_id"], run_id=record["run_id"]
    )
    evidence["evidence_pack"] = {
        "paper_type": "experimental_physics",
        "evidence_quality": "high",
        "coverage": {"missing": [], "ratio": 1.0},
        "evidence_units": [
            {"evidence_id": f"ev:{index}", "types": ["results"], "text": f"result {index}"}
            for index in range(25)
        ],
        "section_texts": {"doc:main:results": "x" * 6000},
    }
    bundle = build_bundle(record, evidence)
    assert len(bundle["evidence_units"]) == 25
    assert len(bundle["section_texts"]["doc:main:results"]) == 6000

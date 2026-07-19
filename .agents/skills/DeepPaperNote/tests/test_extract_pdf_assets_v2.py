from __future__ import annotations

from pathlib import Path

import extract_pdf_assets_v2
import pytest
from common import fitz
from contracts_v2 import artifact_header
from extract_pdf_assets_v2 import _parse_caption_start, extract_paper_record_assets
from figure_contracts_v2 import normalize_figure_label, sha256_file


def _make_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "A searchable page for deterministic asset extraction.")
    document.save(path)
    document.close()
    return path


def _paper_record(
    pdf: Path, *, digest: str | None = None, pages: int = 1
) -> dict:
    artifact = artifact_header(
        "paper_record",
        paper_id="paper-assets",
        run_id="run-assets",
        status="pass",
    )
    artifact["paper_record"] = {
        "paper_id": "paper-assets",
        "metadata": {"title": "Asset integrity fixture"},
        "documents": [
            {
                "document_id": "doc-main",
                "role": "main",
                "path": str(pdf),
                "sha256": digest or sha256_file(pdf),
                "pages": pages,
            }
        ],
    }
    return artifact


def test_sentence_initial_body_reference_is_not_a_caption() -> None:
    assert _parse_caption_start("Figure 3 shows the temperature dependence of conductance.") is None
    assert _parse_caption_start("Table 1 reports all fitted parameters.") is None


def test_punctuated_main_figure_caption_is_detected() -> None:
    parsed = _parse_caption_start("Fig. 3. Temperature dependence of conductance")

    assert parsed is not None
    assert parsed["label"] == "Fig. 3"
    assert parsed["kind"] == "figure"


def test_supplementary_figure_and_table_labels_are_detected() -> None:
    supplemental = _parse_caption_start("Fig. S2 | Additional gate sweeps")
    table = _parse_caption_start("Table S1. Device parameters")

    assert supplemental is not None
    assert normalize_figure_label(supplemental["label"]) == "fig s2"
    assert table is not None
    assert normalize_figure_label(table["label"]) == "table s1"
    assert table["kind"] == "table"


def test_extended_data_figure_caption_is_detected() -> None:
    parsed = _parse_caption_start("Extended Data Figure 4: Control experiment")

    assert parsed is not None
    assert normalize_figure_label(parsed["label"]) == "extended data fig 4"


def test_pdf_asset_extraction_rejects_negative_page_limit(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "paper.pdf")

    with pytest.raises(ValueError, match="max_pages must be non-negative"):
        extract_paper_record_assets(
            _paper_record(pdf), assets_dir=tmp_path / "assets", max_pages=-1
        )


def test_pdf_asset_extraction_rejects_preexisting_source_hash_drift(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "paper.pdf")
    record = _paper_record(pdf, digest="0" * 64)

    artifact = extract_paper_record_assets(record, assets_dir=tmp_path / "assets")

    assert artifact["status"] == "fail"
    assert "pdf_asset_source_hash_mismatch_before:doc-main" in artifact["failures"]
    assert artifact["figure_manifest"]["status"] == "fail"


def test_pdf_asset_extraction_rechecks_source_hash_after_processing(
    tmp_path: Path, monkeypatch
) -> None:
    pdf = _make_pdf(tmp_path / "paper.pdf")
    record = _paper_record(pdf)
    expected = record["paper_record"]["documents"][0]["sha256"]
    digests = iter([expected, "f" * 64])
    monkeypatch.setattr(extract_pdf_assets_v2, "sha256_file", lambda _path: next(digests))

    artifact = extract_paper_record_assets(record, assets_dir=tmp_path / "assets")

    assert artifact["status"] == "fail"
    assert "pdf_asset_source_hash_mismatch_after:doc-main" in artifact["failures"]
    assert artifact["figure_manifest"]["status"] == "fail"


def test_pdf_asset_extraction_rejects_recorded_page_count_drift(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "paper.pdf")
    record = _paper_record(pdf, pages=2)

    artifact = extract_paper_record_assets(record, assets_dir=tmp_path / "assets")

    assert artifact["status"] == "fail"
    assert (
        "pdf_asset_page_count_mismatch:doc-main:expected=2:actual=1"
        in artifact["failures"]
    )
    assert artifact["documents"][0]["pages_processed"] == 0


def test_pdf_asset_extraction_rejects_truncation_instead_of_publishing_partial_assets(
    tmp_path: Path,
) -> None:
    pdf = _make_pdf(tmp_path / "paper.pdf")
    document = fitz.open(pdf)
    document.new_page().insert_text((72, 72), "Second page.")
    document.save(tmp_path / "two-pages.pdf")
    document.close()
    two_pages_pdf = tmp_path / "two-pages.pdf"
    record = _paper_record(two_pages_pdf, pages=2)

    artifact = extract_paper_record_assets(
        record,
        assets_dir=tmp_path / "assets",
        max_pages=1,
    )

    assert artifact["status"] == "fail"
    assert (
        "pdf_asset_document_truncated:doc-main:max_pages=1:total=2"
        in artifact["failures"]
    )
    assert artifact["documents"][0]["pages_processed"] == 0

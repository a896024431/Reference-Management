from __future__ import annotations

from pathlib import Path

import common
from common import (
    clean_local_pdf_stem,
    extract_arxiv_id,
    extract_doi,
    extract_local_pdf_hints,
    normalize_pdf_text_artifacts,
    normalize_title,
    paper_id_for_record,
)


class FakePdfPage:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_text(self, mode: str) -> str:
        assert mode == "text"
        return self.text


class FakePdfDoc:
    def __init__(self, metadata: dict[str, str], pages: list[str]) -> None:
        self.metadata = metadata
        self._pages = [FakePdfPage(text) for text in pages]

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> FakePdfPage:
        return self._pages[index]

    def close(self) -> None:
        return None


class FakeFitz:
    def __init__(self, document: FakePdfDoc) -> None:
        self.document = document

    def open(self, path: Path) -> FakePdfDoc:
        return self.document


def test_local_identity_helpers_extract_doi_arxiv_and_normalize_titles() -> None:
    assert extract_doi("https://doi.org/10.1038/s44184-025-00175-1.") == (
        "10.1038/s44184-025-00175-1"
    )
    assert extract_arxiv_id("https://arxiv.org/abs/2508.09736v4") == "2508.09736"
    assert normalize_title("量子输运：实验") == "量子输运 实验"
    assert paper_id_for_record({"title": "论文甲"}) != paper_id_for_record({"title": "论文乙"})
    assert paper_id_for_record({"doi": "https://doi.org/10.1000/ABC"}) == "doi:10.1000/abc"


def test_common_exposes_no_network_or_provider_entry_points() -> None:
    for name in (
        "http_get_text",
        "http_get_bytes",
        "resolve_reference",
        "enrich_metadata",
        "search_crossref_by_title",
        "search_semantic_scholar",
        "search_openalex_by_title",
    ):
        assert not hasattr(common, name)


def test_clean_local_pdf_stem_removes_zotero_style_noise() -> None:
    stem = (
        "Xu 等 - 2025 - Identifying psychiatric manifestations in outpatients with "
        "depression and anxiety a large language-182952"
    )
    assert clean_local_pdf_stem(stem) == (
        "Identifying psychiatric manifestations in outpatients with depression and "
        "anxiety a large language"
    )


def test_normalize_pdf_text_artifacts_expands_ligatures() -> None:
    assert normalize_pdf_text_artifacts("Efﬁcient ﬂow oﬀers aﬃne aﬄuent") == (
        "Efficient flow offers affine affluent"
    )


def test_extract_local_pdf_hints_prefers_metadata_title_and_doi(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        common,
        "fitz",
        FakeFitz(
            FakePdfDoc(
                metadata={
                    "title": "A local metadata title",
                    "subject": "doi:10.1038/s44184-025-00175-1",
                },
                pages=["Ignored fallback title"],
            )
        ),
    )

    hints = extract_local_pdf_hints(pdf_path)

    assert hints["title"] == "A local metadata title"
    assert hints["title_source"] == "metadata"
    assert hints["doi"] == "10.1038/s44184-025-00175-1"


def test_extract_local_pdf_hints_falls_back_to_first_page_title(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        common,
        "fitz",
        FakeFitz(
            FakePdfDoc(
                metadata={},
                pages=[
                    "\n".join(
                        [
                            "npj | mental health research Article",
                            "https://doi.org/10.1038/s44184-025-00175-1",
                            "LLaMA: Open and Efﬁcient Foundation Language Models",
                            "Hugo Touvron, Thibaut Lavril",
                        ]
                    )
                ],
            )
        ),
    )

    hints = extract_local_pdf_hints(pdf_path)

    assert hints["title"] == "LLaMA: Open and Efficient Foundation Language Models"
    assert hints["title_source"] == "first_page"
    assert hints["doi"] == "10.1038/s44184-025-00175-1"

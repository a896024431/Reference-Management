# ruff: noqa: E501
# Long literals intentionally mirror real metadata fixtures.
from __future__ import annotations

from pathlib import Path

import pytest
from common import (
    clean_local_pdf_stem,
    enrich_metadata,
    env_config_value,
    extract_arxiv_id,
    extract_doi,
    extract_local_pdf_hints,
    fetch_arxiv_entries,
    infer_source_type,
    merge_metadata_records,
    normalize_openalex_work,
    normalize_pdf_text_artifacts,
    normalize_title,
    paper_id_for_record,
    resolve_reference,
    semantic_scholar_headers,
    title_resolution,
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
    def __init__(self, doc: FakePdfDoc) -> None:
        self.doc = doc

    def open(self, path: Path) -> FakePdfDoc:
        return self.doc


def test_extract_doi_from_url_like_text() -> None:
    text = "Published version: https://doi.org/10.1038/s44184-025-00175-1."
    assert extract_doi(text) == "10.1038/s44184-025-00175-1"


def test_extract_arxiv_id_strips_version() -> None:
    text = "https://arxiv.org/abs/2508.09736v4"
    assert extract_arxiv_id(text) == "2508.09736"


def test_unicode_titles_and_authors_keep_stable_identity() -> None:
    assert normalize_title("量子输运：实验") == "量子输运 实验"
    assert paper_id_for_record({"title": "论文甲"}) != paper_id_for_record({"title": "论文乙"})
    assert paper_id_for_record({"doi": "https://doi.org/10.1000/ABC"}) == "doi:10.1000/abc"
    merged = merge_metadata_records({"title": "量子输运", "authors": ["张三", "Élodie"]})
    assert merged["authors"] == ["张三", "Élodie"]


def test_title_resolution_keeps_conflicting_dois_ambiguous() -> None:
    title = "A Shared Paper"
    resolution = title_resolution(
        title,
        [
            {"title": title, "year": "2025", "doi": "10.1000/a"},
            {"title": title, "year": "2025", "doi": "10.1000/b"},
        ],
    )
    assert resolution["status"] == "ambiguous"
    assert {candidate["doi"] for candidate in resolution["candidates"]} == {
        "10.1000/a",
        "10.1000/b",
    }


def test_infer_source_type_for_local_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    assert infer_source_type(str(pdf_path)) == "local_pdf"


@pytest.mark.parametrize(
    "url",
    (
        "https://example.org/paper.pdf?download=1",
        "https://example.org/PAPER.PDF#page=2",
        "https://example.org/10.1000/example.pdf?token=abc",
    ),
)
def test_infer_source_type_for_direct_pdf_url_uses_url_path(url: str) -> None:
    assert infer_source_type(url) == "pdf_url"


def test_clean_local_pdf_stem_removes_zotero_style_noise() -> None:
    stem = "Xu 等 - 2025 - Identifying psychiatric manifestations in outpatients with depression and anxiety a large language-182952"
    assert (
        clean_local_pdf_stem(stem)
        == "Identifying psychiatric manifestations in outpatients with depression and anxiety a large language"
    )


def test_normalize_pdf_text_artifacts_expands_ligatures() -> None:
    assert (
        normalize_pdf_text_artifacts("Efﬁcient ﬂow oﬀers aﬃne aﬄuent")
        == "Efficient flow offers affine affluent"
    )


def test_extract_local_pdf_hints_prefers_pdf_metadata_title_and_doi(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_doc = FakePdfDoc(
        metadata={
            "title": "Identifying psychiatric manifestations in outpatients with depression and anxiety: a large language model-based approach",
            "subject": "npj Mental Health Research, doi:10.1038/s44184-025-00175-1",
        },
        pages=["Ignored fallback title"],
    )
    monkeypatch.setattr("common.fitz", FakeFitz(fake_doc))

    hints = extract_local_pdf_hints(pdf_path)

    assert (
        hints["title"]
        == "Identifying psychiatric manifestations in outpatients with depression and anxiety: a large language model-based approach"
    )
    assert hints["title_source"] == "metadata"
    assert hints["doi"] == "10.1038/s44184-025-00175-1"


def test_extract_local_pdf_hints_falls_back_to_first_page_title(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_doc = FakePdfDoc(
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
    monkeypatch.setattr("common.fitz", FakeFitz(fake_doc))

    hints = extract_local_pdf_hints(pdf_path)

    assert hints["title"] == "LLaMA: Open and Efficient Foundation Language Models"
    assert hints["title_source"] == "first_page"
    assert hints["doi"] == "10.1038/s44184-025-00175-1"


def test_resolve_reference_local_pdf_uses_extracted_hints(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        "common.extract_local_pdf_hints",
        lambda path: {
            "title": "LLaMA: Open and Efficient Foundation Language Models",
            "doi": "10.48550/arXiv.2302.13971",
            "arxiv_id": "2302.13971",
        },
    )

    resolved = resolve_reference(str(pdf_path))

    assert resolved["source_type"] == "local_pdf"
    assert resolved["title"] == "LLaMA: Open and Efficient Foundation Language Models"
    assert resolved["doi"] == "10.48550/arXiv.2302.13971"
    assert resolved["arxiv_id"] == "2302.13971"


def test_resolve_reference_rejects_unstructured_article_url() -> None:
    resolved = resolve_reference("https://example.org/publisher/article")

    assert resolved["status"] == "unsupported_url"
    assert resolved["source_type"] == "url"
    assert resolved["resolution_candidates"] == []


def test_openalex_landing_page_is_not_treated_as_pdf() -> None:
    normalized = normalize_openalex_work(
        {
            "display_name": "Example Paper",
            "primary_location": {},
            "best_oa_location": {
                "pdf_url": None,
                "landing_page_url": "https://example.org/article",
            },
        }
    )

    assert normalized["pdf_url"] == ""


def test_env_config_value_uses_process_environment_only(monkeypatch) -> None:
    monkeypatch.setenv("DEEPPAPERNOTE_SEMANTIC_SCHOLAR_API_KEY", "process_key")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "fallback_key")

    assert env_config_value("DEEPPAPERNOTE_SEMANTIC_SCHOLAR_API_KEY") == "process_key"
    assert semantic_scholar_headers()["x-api-key"] == "process_key"


def test_env_config_value_uses_explicit_default(monkeypatch) -> None:
    monkeypatch.delenv("DEEPPAPERNOTE_SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    assert (
        env_config_value(
            "DEEPPAPERNOTE_SEMANTIC_SCHOLAR_API_KEY",
            "SEMANTIC_SCHOLAR_API_KEY",
            default="",
        )
        == ""
    )
    assert "x-api-key" not in semantic_scholar_headers()


def test_fetch_arxiv_entries_returns_empty_on_http_error(monkeypatch) -> None:
    def raising_http_get_text(*args: object, **kwargs: object) -> str:
        raise RuntimeError("network down")

    monkeypatch.setattr("common.http_get_text", raising_http_get_text)

    assert fetch_arxiv_entries(search_query='ti:"test"', max_results=1) == []


def test_fetch_arxiv_entries_returns_empty_on_invalid_xml(monkeypatch) -> None:
    monkeypatch.setattr("common.http_get_text", lambda *args, **kwargs: "<not-xml")

    assert fetch_arxiv_entries(search_query='ti:"test"', max_results=1) == []


def test_resolve_reference_title_survives_arxiv_failure(monkeypatch) -> None:
    semantic_match = {
        "title": "Example Paper",
        "authors": ["Alice Example"],
        "abstract": "Strong abstract",
        "venue": "ExampleConf",
        "year": "2025",
        "metadata_sources": ["semantic_scholar"],
    }
    monkeypatch.setattr("common.search_semantic_scholar", lambda *args, **kwargs: [semantic_match])
    monkeypatch.setattr("common.search_crossref_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_openalex_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "common.fetch_arxiv_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("arxiv down")),
    )

    resolved = resolve_reference("Example Paper")

    assert resolved["status"] == "ok"
    assert resolved["title"] == "Example Paper"
    assert "semantic_scholar" in (resolved.get("metadata_sources") or [])


def test_enrich_metadata_survives_arxiv_failure(monkeypatch) -> None:
    semantic_match = {
        "title": "Example Paper",
        "authors": ["Alice Example", "Bob Example"],
        "abstract": "Strong abstract",
        "venue": "ExampleConf",
        "year": "2025",
        "doi": "10.1000/example",
        "metadata_sources": ["semantic_scholar"],
    }
    monkeypatch.setattr("common.search_semantic_scholar", lambda *args, **kwargs: [semantic_match])
    monkeypatch.setattr("common.search_crossref_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_openalex_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "common.fetch_arxiv_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("arxiv down")),
    )

    enriched = enrich_metadata(
        {"title": "Example Paper", "arxiv_id": "2501.00001", "metadata_sources": ["seed_record"]}
    )

    assert enriched["title"] == "Example Paper"
    assert enriched["doi"] == "10.1000/example"
    assert enriched["venue"] == "ExampleConf"
    assert enriched["year"] == "2025"
    assert enriched["abstract"] == "Strong abstract"


def test_enrich_metadata_local_pdf_corrects_artifact_title_and_fills_arxiv(monkeypatch) -> None:
    semantic_match = {
        "title": "LLaMA: Open and Efficient Foundation Language Models",
        "authors": ["Hugo Touvron", "Thibaut Lavril"],
        "venue": "arXiv.org",
        "year": "2023",
        "doi": "10.48550/arXiv.2302.13971",
        "arxiv_id": "2302.13971",
        "metadata_sources": ["semantic_scholar"],
        "source": "semantic_scholar",
        "source_type": "semantic_scholar",
        "source_url": "https://www.semanticscholar.org/paper/llama",
    }
    monkeypatch.setattr("common.search_semantic_scholar", lambda *args, **kwargs: [semantic_match])
    monkeypatch.setattr("common.search_crossref_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_openalex_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.safe_fetch_arxiv_entries", lambda *args, **kwargs: [])

    enriched = enrich_metadata(
        {
            "source_type": "local_pdf",
            "title": "Touvron 等 - 2023 - LLaMA Open and Efficient Foundation Language Models-824666",
            "local_pdf_path": "/tmp/llama.pdf",
            "metadata_sources": ["local_pdf"],
        }
    )

    assert enriched["title"] == "LLaMA: Open and Efficient Foundation Language Models"
    assert enriched["doi"] == "10.48550/arXiv.2302.13971"
    assert enriched["arxiv_id"] == "2302.13971"
    assert "semantic_scholar" in enriched["metadata_sources"]


def test_enrich_metadata_local_pdf_prefers_published_doi_over_preprint(monkeypatch) -> None:
    published = {
        "title": "Identifying psychiatric manifestations in outpatients with depression and anxiety: a large language model-based approach",
        "authors": ["Shihao Xu"],
        "venue": "npj Mental Health Research",
        "year": "2025",
        "doi": "10.1038/s44184-025-00175-1",
        "metadata_sources": ["crossref"],
        "source": "crossref",
        "source_type": "crossref",
        "source_url": "https://doi.org/10.1038/s44184-025-00175-1",
    }
    preprint = {
        "title": "Identifying Psychiatric Manifestations in Outpatients with Depression and Anxiety: A Large Language Model-Based Approach",
        "authors": ["Shihao Xu"],
        "venue": "",
        "year": "2025",
        "doi": "10.1101/2025.01.03.24318117",
        "metadata_sources": ["crossref"],
        "source": "crossref",
        "source_type": "crossref",
        "source_url": "https://doi.org/10.1101/2025.01.03.24318117",
    }
    monkeypatch.setattr("common.search_semantic_scholar", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_openalex_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.safe_fetch_arxiv_entries", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "common.search_crossref_by_title", lambda *args, **kwargs: [preprint, published]
    )

    enriched = enrich_metadata(
        {
            "source_type": "local_pdf",
            "title": "Xu 等 - 2025 - Identifying psychiatric manifestations in outpatients with depression and anxiety a large language-182952",
            "local_pdf_path": "/tmp/mental_health.pdf",
            "metadata_sources": ["local_pdf"],
        }
    )

    assert (
        enriched["title"]
        == "Identifying psychiatric manifestations in outpatients with depression and anxiety: a large language model-based approach"
    )
    assert enriched["doi"] == "10.1038/s44184-025-00175-1"
    assert enriched["venue"] == "npj Mental Health Research"


def test_enrich_metadata_backfills_arxiv_doi_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("common.safe_fetch_arxiv_entries", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_semantic_scholar", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_crossref_by_title", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.search_openalex_by_title", lambda *args, **kwargs: [])
    enriched = enrich_metadata(
        {"title": "Example Paper", "arxiv_id": "2302.13971", "metadata_sources": ["seed_record"]}
    )
    assert enriched["doi"] == "10.48550/arXiv.2302.13971"


def test_resolve_reference_arxiv_id_survives_arxiv_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "common.fetch_arxiv_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("arxiv down")),
    )

    resolved = resolve_reference("2501.00001")

    assert resolved["status"] == "unresolved"
    assert resolved["source_type"] == "title_query"
    assert resolved["resolution_candidates"] == []


def test_resolve_reference_arxiv_url_survives_arxiv_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "common.fetch_arxiv_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("arxiv down")),
    )

    resolved = resolve_reference("https://arxiv.org/abs/2501.00001")

    assert resolved["status"] == "unresolved"
    assert resolved["source_type"] == "title_query"
    assert resolved["resolution_candidates"] == []

from __future__ import annotations

from extract_pdf_assets_v2 import _parse_caption_start
from figure_contracts import normalize_figure_label


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

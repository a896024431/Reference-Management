# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from extract_evidence_contract_v2 import infer_release_profile


def test_universal_chiral_luttinger_paper_remains_experimental() -> None:
    metadata = {
        "title": (
            "Universal chiral Luttinger liquid behavior in a graphene fractional "
            "quantum Hall point contact"
        )
    }
    units = [
        {
            "text": (
                "We measured the temperature dependence of the conductance and the "
                "bias voltage response of a graphene device. The observed data show "
                "universal scaling described by a Luttinger model."
            )
        }
    ]
    paper_type, rationale = infer_release_profile(metadata, units)
    assert paper_type == "experimental_physics"
    assert "theoretical interpretation does not override" in rationale


def test_fabrication_title_keeps_materials_profile() -> None:
    metadata = {"title": "Nanoscale electrostatic control by local anodic oxidation"}
    units = [{"text": "We measured conductance in the fabricated device."}]
    assert infer_release_profile(metadata, units)[0] == "materials_fabrication"

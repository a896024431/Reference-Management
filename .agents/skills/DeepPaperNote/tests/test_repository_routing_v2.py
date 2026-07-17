from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from configure_repository_v2 import (  # noqa: E402
    AGENTS_V2_BLOCK,
    GITIGNORE_BLOCK,
    README_V2_BLOCK,
)


def test_repository_configurator_routes_to_final_v2_entrypoint() -> None:
    assert "scripts/run_pipeline_final_v2.py" in AGENTS_V2_BLOCK
    assert "scripts/run_pipeline_v2.py" not in AGENTS_V2_BLOCK
    assert r"scripts\run_pipeline_final_v2.py" in README_V2_BLOCK
    assert r"scripts\run_pipeline_v2.py" not in README_V2_BLOCK


def test_repository_configurator_keeps_generated_outputs_local() -> None:
    assert ".local/" in GITIGNORE_BLOCK
    assert "tmp/" in GITIGNORE_BLOCK
    assert "DeepPaperNote_output/" in GITIGNORE_BLOCK

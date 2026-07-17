"""Import-safe facade for :mod:`extract_evidence_v2.py`.

The add-only migration keeps the executable script at the sibling path while
this package exposes the canonical library API.  Result evidence is ordered by
actual Results-section evidence before numeric protocol details.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parent.parent / "extract_evidence_v2.py"
_SPEC = importlib.util.spec_from_file_location("_deeppapernote_extract_evidence_v2", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load {_SCRIPT}")
_IMPL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPL)

for _name in dir(_IMPL):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_IMPL, _name)


def build_evidence_artifact(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _IMPL.fitz = globals().get("fitz")
    artifact = _IMPL.build_evidence_artifact(*args, **kwargs)
    pack = artifact.get("evidence_pack", {})
    results = pack.get("results_evidence", []) if isinstance(pack, dict) else []
    if isinstance(results, list):
        results.sort(
            key=lambda item: (
                0 if isinstance(item, dict) and item.get("source_section") == "results" else 1,
                int(item.get("page", 0)) if isinstance(item, dict) else 0,
            )
        )
    return artifact


def main() -> None:
    _IMPL.fitz = globals().get("fitz")
    _IMPL.main()


__all__ = [name for name in globals() if not name.startswith("_")]

#!/usr/bin/env python3
"""Render run-local contact sheets for canonical v2 figure candidates."""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
from contracts_v2 import (
    ContractError,
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
)
from figure_contracts_v2 import (
    normalize_figure_decisions,
    normalize_figure_label,
    normalize_figure_manifest,
    sha256_file,
)
from figure_visual_review_contracts_v2 import canonical_json_sha256

PAGE_WIDTH = 1600
PAGE_HEIGHT = 1800
MARGIN = 42
HEADER_HEIGHT = 56
GAP = 24
DEFAULT_COLUMNS = 2
DEFAULT_ROWS = 3
QUALITY_COLORS = {
    "usable": (0.10, 0.55, 0.22),
    "reject": (0.78, 0.16, 0.14),
    "unknown": (0.45, 0.45, 0.45),
}


class ContactSheetError(ContractError):
    """Raised when a contact sheet would leave the run-local boundary."""


def _quality_status(asset: dict[str, Any]) -> str:
    signals = asset.get("quality_signals")
    if not isinstance(signals, dict):
        return "unknown"
    value = str(signals.get("visual_quality_status", "unknown")).strip().lower()
    return value if value in {"usable", "reject"} else "unknown"


def _ascii(value: object) -> str:
    """Keep built-in Helvetica rendering deterministic on every platform."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _validate_run_dir(run_dir: Path, run_id: str) -> Path:
    resolved = run_dir.expanduser().resolve()
    lowered = [part.casefold() for part in resolved.parts]
    sequence = [".local", "deeppapernote", "runs", run_id.casefold()]
    matches = any(lowered[index : index + 4] == sequence for index in range(len(lowered) - 3))
    if not matches or resolved.name != run_id:
        raise ContactSheetError("Contact sheets must stay under .local/deeppapernote/runs/<run_id>")
    if any(part.casefold() == "research" for part in resolved.parts):
        raise ContactSheetError("Contact sheets must never be written under Research")
    return resolved


def _candidate_roles(decisions: dict[str, Any]) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = defaultdict(set)
    for decision in decisions.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        selected = str(decision.get("selected_asset_id", "")).strip()
        recommended = str(decision.get("recommended_asset_id", "")).strip()
        if selected:
            roles[selected].add("selected")
        if recommended:
            roles[recommended].add("recommended")
        for asset_id in decision.get("candidate_asset_ids", []) or []:
            if str(asset_id).strip():
                roles[str(asset_id).strip()].add("candidate")
        for asset_id in decision.get("rejected_asset_ids", []) or []:
            if str(asset_id).strip():
                roles[str(asset_id).strip()].add("rejected")
    return roles


def _candidate_status(asset_id: str, roles: dict[str, set[str]]) -> str:
    order = ("selected", "recommended", "candidate", "rejected")
    present = roles.get(asset_id, set())
    return "+".join(role for role in order if role in present) or "unreferenced"


def _group_assets(
    manifest: dict[str, Any], decisions: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roles = _candidate_roles(decisions)
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    source_hashes: dict[str, str] = {}
    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict):
            continue
        quality = _quality_status(asset)
        if quality not in {"usable", "reject"}:
            continue
        source = Path(str(asset.get("path", ""))).expanduser().resolve()
        if not source.is_file():
            raise ContactSheetError(f"Figure source is missing: {source}")
        actual_hash = sha256_file(source)
        expected_hash = str(asset.get("file_sha256", ""))
        if actual_hash != expected_hash:
            raise ContactSheetError(f"Figure source hash mismatch: {asset.get('asset_id', '')}")
        source_hashes[str(source)] = actual_hash
        key = (
            normalize_figure_label(str(asset.get("label", ""))),
            str(asset.get("document_id", "")),
            int(asset.get("page_number", 0) or 0),
        )
        grouped[key].append(dict(asset))

    groups: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    role_priority = {"selected": 0, "recommended": 1, "candidate": 2, "rejected": 3}
    for group_number, key in enumerate(sorted(grouped), start=1):
        label, document_id, page_number = key
        assets = sorted(
            grouped[key],
            key=lambda asset: (
                min(
                    (
                        role_priority.get(role, 9)
                        for role in roles.get(str(asset.get("asset_id", "")), set())
                    ),
                    default=9,
                ),
                0 if _quality_status(asset) == "usable" else 1,
                str(asset.get("asset_id", "")),
            ),
        )
        group_id = f"group-{group_number:03d}"
        asset_ids = [str(asset.get("asset_id", "")) for asset in assets]
        groups.append(
            {
                "group_id": group_id,
                "normalized_label": label,
                "label": str(assets[0].get("label", label)) if assets else label,
                "document_id": document_id,
                "page_number": page_number,
                "asset_ids": asset_ids,
            }
        )
        for asset in assets:
            asset_id = str(asset.get("asset_id", ""))
            cells.append(
                {
                    "asset_id": asset_id,
                    "group_id": group_id,
                    "label": str(asset.get("label", "")),
                    "document_id": document_id,
                    "page_number": page_number,
                    "quality": _quality_status(asset),
                    "candidate_status": _candidate_status(asset_id, roles),
                    "source_path": str(Path(str(asset.get("path", ""))).expanduser().resolve()),
                    "source_sha256": str(asset.get("file_sha256", "")),
                }
            )

    for source_path, before_hash in source_hashes.items():
        if sha256_file(source_path) != before_hash:
            raise ContactSheetError(
                f"Contact-sheet rendering modified a source image: {source_path}"
            )
    return groups, cells


def _draw_cell(page: fitz.Page, rect: fitz.Rect, cell: dict[str, Any]) -> None:
    quality = str(cell["quality"])
    border_color = QUALITY_COLORS.get(quality, QUALITY_COLORS["unknown"])
    page.draw_rect(rect, color=border_color, width=4)
    text_height = 145
    image_rect = fitz.Rect(rect.x0 + 10, rect.y0 + 10, rect.x1 - 10, rect.y1 - text_height)
    page.insert_image(
        image_rect,
        filename=str(cell["source_path"]),
        keep_proportion=True,
    )
    metadata_rect = fitz.Rect(rect.x0 + 12, rect.y1 - text_height + 8, rect.x1 - 12, rect.y1 - 8)
    lines = [
        f"asset_id: {_ascii(cell['asset_id'])}",
        f"label: {_ascii(cell['label'])}",
        f"document/page: {_ascii(cell['document_id'])} / {cell['page_number']}",
        f"quality: {quality} | candidate: {_ascii(cell['candidate_status'])}",
        f"group: {_ascii(cell['group_id'])}",
    ]
    page.insert_textbox(
        metadata_rect,
        "\n".join(lines),
        fontname="helv",
        fontsize=11,
        lineheight=1.15,
        color=(0.05, 0.05, 0.05),
    )


def _render_sheet_page(
    *,
    page_number: int,
    cells: list[dict[str, Any]],
    output_path: Path,
    columns: int,
    rows: int,
) -> None:
    document = fitz.open()
    try:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text(
            (MARGIN, 38),
            f"DeepPaperNote Figure Contact Sheet - page {page_number}",
            fontname="helv",
            fontsize=18,
            color=(0.05, 0.05, 0.05),
        )
        available_width = PAGE_WIDTH - 2 * MARGIN - (columns - 1) * GAP
        available_height = PAGE_HEIGHT - MARGIN - HEADER_HEIGHT - (rows - 1) * GAP
        cell_width = available_width / columns
        cell_height = available_height / rows
        for index, cell in enumerate(cells):
            row, column = divmod(index, columns)
            x0 = MARGIN + column * (cell_width + GAP)
            y0 = HEADER_HEIGHT + row * (cell_height + GAP)
            rect = fitz.Rect(x0, y0, x0 + cell_width, y0 + cell_height)
            _draw_cell(page, rect, cell)
        pixmap = page.get_pixmap(alpha=False)
        pixmap.set_dpi(72, 72)
        temporary = output_path.with_name(output_path.stem + ".tmp" + output_path.suffix)
        pixmap.save(temporary, output="png")
        os.replace(temporary, output_path)
    finally:
        document.close()


def build_contact_sheet(
    *,
    manifest: dict[str, Any],
    decisions: dict[str, Any],
    run_dir: str | Path,
    columns: int = DEFAULT_COLUMNS,
    rows: int = DEFAULT_ROWS,
) -> dict[str, Any]:
    """Build PNG sheets plus a v2 JSON index without changing source images."""
    if columns < 1 or rows < 1:
        raise ContactSheetError("columns and rows must both be positive")
    canonical_manifest = normalize_figure_manifest(manifest, verify_files=True)
    canonical_decisions = normalize_figure_decisions(
        decisions,
        manifest=canonical_manifest,
        require_final=False,
    )
    paper_id, run_id = require_same_identity(canonical_manifest, canonical_decisions)
    resolved_run_dir = _validate_run_dir(Path(run_dir), run_id)
    output_dir = resolved_run_dir / "figure-review" / "contact-sheets"
    output_dir.mkdir(parents=True, exist_ok=True)
    groups, cells = _group_assets(canonical_manifest, canonical_decisions)

    page_size = columns * rows
    sheets: list[dict[str, Any]] = []
    for offset in range(0, len(cells), page_size):
        page_cells = cells[offset : offset + page_size]
        sheet_page = offset // page_size + 1
        path = output_dir / f"contact-sheet-{sheet_page:03d}.png"
        _render_sheet_page(
            page_number=sheet_page,
            cells=page_cells,
            output_path=path,
            columns=columns,
            rows=rows,
        )
        with fitz.open(path) as rendered:
            if (
                rendered.page_count != 1
                or rendered[0].rect.width < 1
                or rendered[0].rect.height < 1
            ):
                raise ContactSheetError(f"Rendered contact sheet is not decodable: {path}")
        for local_index, cell in enumerate(page_cells):
            cell["sheet_page"] = sheet_page
            cell["cell_index"] = local_index
        sheets.append(
            {
                "sheet_page": sheet_page,
                "path": str(path),
                "relative_path": path.relative_to(resolved_run_dir).as_posix(),
                "sha256": sha256_file(path),
                "width": PAGE_WIDTH,
                "height": PAGE_HEIGHT,
                "asset_ids": [cell["asset_id"] for cell in page_cells],
            }
        )

    artifact = artifact_header(
        "figure_contact_sheet",
        paper_id=paper_id,
        run_id=run_id,
        status="pass",
    )
    artifact.update(
        {
            "hash_method": "canonical-json-v1",
            "manifest_sha256": canonical_json_sha256(canonical_manifest),
            "decisions_sha256": canonical_json_sha256(canonical_decisions),
            "run_dir": str(resolved_run_dir),
            "layout": {"columns": columns, "rows": rows, "cells_per_sheet": page_size},
            "groups": groups,
            "cells": cells,
            "sheets": sheets,
        }
    )
    return artifact


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--manifest", required=True)
    command.add_argument("--decisions", required=True)
    command.add_argument("--run-dir", required=True)
    command.add_argument("--output", default="")
    command.add_argument("--columns", type=int, default=DEFAULT_COLUMNS)
    command.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    return command


def main() -> None:
    args = parser().parse_args()
    artifact = build_contact_sheet(
        manifest=load_json_object(args.manifest),
        decisions=load_json_object(args.decisions),
        run_dir=args.run_dir,
        columns=args.columns,
        rows=args.rows,
    )
    output = args.output or str(
        Path(args.run_dir).expanduser().resolve() / "figure-review" / "figure_contact_sheet.json"
    )
    emit_json(artifact, output)


if __name__ == "__main__":
    main()

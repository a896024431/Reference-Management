#!/usr/bin/env python3
"""Canonical contact-sheet entrypoint with atomic PNG rendering."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import build_figure_contact_sheet_v2 as _core
import fitz
from contracts_v2 import emit_json, load_json_object


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
        page = document.new_page(width=_core.PAGE_WIDTH, height=_core.PAGE_HEIGHT)
        page.insert_text(
            (_core.MARGIN, 38),
            f"DeepPaperNote Figure Contact Sheet - page {page_number}",
            fontname="helv",
            fontsize=18,
            color=(0.05, 0.05, 0.05),
        )
        available_width = _core.PAGE_WIDTH - 2 * _core.MARGIN - (columns - 1) * _core.GAP
        available_height = (
            _core.PAGE_HEIGHT - _core.MARGIN - _core.HEADER_HEIGHT - (rows - 1) * _core.GAP
        )
        cell_width = available_width / columns
        cell_height = available_height / rows
        for index, cell in enumerate(cells):
            row, column = divmod(index, columns)
            x0 = _core.MARGIN + column * (cell_width + _core.GAP)
            y0 = _core.HEADER_HEIGHT + row * (cell_height + _core.GAP)
            rect = fitz.Rect(x0, y0, x0 + cell_width, y0 + cell_height)
            _core._draw_cell(page, rect, cell)
        pixmap = page.get_pixmap(alpha=False)
        pixmap.set_dpi(72, 72)
        temporary = output_path.with_name(output_path.stem + ".tmp" + output_path.suffix)
        pixmap.save(temporary, output="png")
        os.replace(temporary, output_path)
    finally:
        document.close()


_core._render_sheet_page = _render_sheet_page
build_contact_sheet = _core.build_contact_sheet


def main() -> None:
    args = _core.parser().parse_args()
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

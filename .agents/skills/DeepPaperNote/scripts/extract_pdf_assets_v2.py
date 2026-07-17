#!/usr/bin/env python3
"""Extract collision-proof, caption-anchored PDF visual assets (schema v2).

This module reuses the mature crop and visual-quality heuristics from the MVP
extractor while fixing its identity and caption-detection failure modes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import extract_pdf_assets as legacy
from common import default_assets_dir, emit, fitz, normalize_whitespace
from figure_contracts import (
    FIGURE_SCHEMA_VERSION,
    build_figure_asset_identity,
    make_figure_manifest,
    sha256_bytes,
    sha256_file,
)

CAPTION_START_RE = re.compile(
    r"^(?P<label>(?:extended\s+data\s+fig(?:ure)?|supplementary\s+fig(?:ure)?|fig(?:ure)?|table)"
    r"\.?\s*(?:s\s*)?\d+[a-z]?)(?=\s|[.:|\-\u2013\u2014]|$)"
    r"(?P<separator>\s*(?:[.:|\-\u2013\u2014]\s*)?)(?P<rest>.*)$",
    re.IGNORECASE,
)

BODY_REFERENCE_VERBS = {
    "can",
    "compares",
    "contains",
    "demonstrates",
    "depicts",
    "describes",
    "displays",
    "gives",
    "illustrates",
    "indicates",
    "is",
    "lists",
    "plots",
    "presents",
    "provides",
    "reports",
    "reveals",
    "shows",
    "summarizes",
    "was",
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "extract pdf assets v2")
    p.add_argument(
        "--input",
        required=True,
        help="Fetch/paper-record JSON, JSON string, or raw paper reference.",
    )
    p.add_argument("--output", default="", help="Output JSON path.")
    p.add_argument("--assets-dir", default="", help="Optional explicit assets directory.")
    p.add_argument(
        "--max-pages", type=int, default=0, help="Maximum pages to scan; 0 scans the full document."
    )
    p.add_argument("--min-searchable-chars", type=int, default=100)
    p.add_argument("--ocr-dpi", type=int, default=300)
    p.add_argument("--figure-dpi", type=int, default=legacy.FIGURE_RENDER_DPI)
    return p


def _parse_caption_start(text: str) -> dict[str, str] | None:
    """Parse a real caption start and reject sentence-initial body references."""
    line = normalize_whitespace(text)
    match = CAPTION_START_RE.match(line)
    if not match:
        return None
    label = normalize_whitespace(match.group("label"))
    separator = match.group("separator") or ""
    rest = normalize_whitespace(match.group("rest"))
    has_caption_delimiter = bool(re.search(r"[.:|\-\u2013\u2014]", separator))
    first_word_match = re.match(r"([A-Za-z]+)", rest)
    first_word = first_word_match.group(1).lower() if first_word_match else ""
    if not has_caption_delimiter and first_word in BODY_REFERENCE_VERBS:
        return None
    return {
        "label": label,
        "kind": legacy._classify_caption_kind(label),
        "rest": rest,
        "separator": separator,
    }


def _find_caption_blocks(page) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    for block in blocks:
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        for line_index, line in enumerate(lines):
            spans = line.get("spans", [])
            if not spans:
                continue
            line_text = "".join(span.get("text", "") for span in spans).strip()
            parsed = _parse_caption_start(line_text)
            if parsed is None:
                continue
            caption_lines = [line_text]
            x0, y0, x1, y1 = line["bbox"]
            previous_bottom = y1
            line_height = max(y1 - y0, 6.0)
            for continuation in lines[line_index + 1 :]:
                continuation_spans = continuation.get("spans", [])
                if not continuation_spans:
                    break
                continuation_text = "".join(
                    span.get("text", "") for span in continuation_spans
                ).strip()
                if not continuation_text or _parse_caption_start(continuation_text):
                    break
                if legacy._looks_like_data_row(continuation_text):
                    break
                cb = continuation["bbox"]
                if cb[1] - previous_bottom > line_height * 1.6:
                    break
                x0 = min(x0, cb[0])
                x1 = max(x1, cb[2])
                y1 = max(y1, cb[3])
                previous_bottom = cb[3]
                caption_lines.append(continuation_text)
            anchors.append(
                {
                    "label": parsed["label"],
                    "kind": parsed["kind"],
                    "bbox": (x0, y0, x1, y1),
                    "line_text": " ".join(caption_lines),
                    "caption_detection": "anchored_label_v2",
                }
            )
    anchors.sort(key=lambda anchor: (anchor["bbox"][1], anchor["bbox"][0]))
    return anchors


def _resolve_document(record: dict[str, Any], pdf_path: Path) -> tuple[str, str]:
    resolved_pdf = pdf_path.resolve()
    for document in record.get("documents", []) or []:
        if not isinstance(document, dict):
            continue
        candidate = str(document.get("path", "") or document.get("pdf_path", "")).strip()
        try:
            matches = bool(candidate) and Path(candidate).expanduser().resolve() == resolved_pdf
        except OSError:
            matches = False
        if matches:
            return (
                str(document.get("document_id", "") or "main"),
                str(document.get("role", "") or "main"),
            )
    return (
        str(record.get("document_id", "") or "main"),
        str(record.get("document_role", "") or "main"),
    )


def _stable_run_identity(record: dict[str, Any], pdf_path: Path) -> tuple[str, str, str]:
    pdf_hash = sha256_file(pdf_path)
    paper_id = str(record.get("paper_id", "")).strip()
    if not paper_id:
        identity_seed = str(record.get("title", "")).strip() or pdf_hash
        paper_id = f"paper-{sha256_bytes(identity_seed.encode('utf-8'))[:16]}"
    run_id = str(record.get("run_id", "")).strip() or f"run-{paper_id}-{pdf_hash[:12]}"
    return paper_id, run_id, pdf_hash


def extract_page_images_v2(
    doc,
    page,
    page_number: int,
    images_dir: Path,
    *,
    document_id: str,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen_xrefs: set[int] = set()
    for image_index, image_info in enumerate(page.get_images(full=True), start=1):
        if not image_info:
            continue
        xref = int(image_info[0])
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        extracted = doc.extract_image(xref)
        image_bytes = extracted.get("image")
        if not image_bytes:
            continue
        extension = normalize_whitespace(str(extracted.get("ext", "png"))).lower() or "png"
        content_hash = sha256_bytes(image_bytes)
        asset_id, filename, identity_hash = build_figure_asset_identity(
            document_id=document_id,
            page_number=page_number,
            label=f"xref {xref} image {image_index}",
            bbox=[xref, image_index],
            extraction_level="xref",
            content_sha256=content_hash,
            extension=extension,
        )
        output_path = images_dir / filename
        legacy.save_image_bytes(output_path, image_bytes)
        assets.append(
            {
                "asset_id": asset_id,
                "document_id": document_id,
                "page_number": page_number,
                "image_index": image_index,
                "xref": xref,
                "label": f"xref {xref}",
                "filename": filename,
                "path": str(output_path),
                "ext": extension,
                "width": extracted.get("width", 0),
                "height": extracted.get("height", 0),
                "colorspace": extracted.get("colorspace", 0),
                "size_bytes": len(image_bytes),
                "extraction_level": "xref",
                "bbox_sha256": identity_hash,
                "file_sha256": content_hash,
            }
        )
    return assets


def extract_figure_regions_v2(
    page,
    page_number: int,
    images_dir: Path,
    *,
    document_id: str,
    dpi: int = legacy.FIGURE_RENDER_DPI,
) -> list[dict[str, Any]]:
    if fitz is None:
        return []
    anchors = _find_caption_blocks(page)
    if not anchors:
        return []
    page_rect = page.rect
    assets: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        previous = anchors[index - 1] if index > 0 else None
        following = anchors[index + 1] if index + 1 < len(anchors) else None
        kind = anchor.get("kind", "figure")
        bbox = None
        table_body_rows = 0
        if kind == "table":
            table_result = legacy._estimate_table_bbox_with_rows(
                page, anchor, previous, following, page_rect
            )
            if table_result is not None:
                bbox, table_body_rows = table_result
            if bbox is None:
                bbox = legacy._estimate_figure_bbox_above_caption(page, anchor, previous, page_rect)
        else:
            bbox = legacy._estimate_figure_bbox_above_caption(page, anchor, previous, page_rect)
            if bbox is None:
                bbox = legacy._estimate_table_bbox(page, anchor, previous, following, page_rect)
        if bbox is None:
            continue
        try:
            png_bytes = legacy._render_crop(page, bbox, dpi)
        except Exception:
            continue
        content_hash = sha256_bytes(png_bytes)
        asset_id, filename, crop_hash = build_figure_asset_identity(
            document_id=document_id,
            page_number=page_number,
            label=str(anchor["label"]),
            bbox=bbox,
            extraction_level="figure",
            content_sha256=content_hash,
            extension="png",
        )
        output_path = images_dir / filename
        legacy.save_image_bytes(output_path, png_bytes)
        quality_signals = legacy._quality_signals_for_crop(
            page,
            kind,
            bbox,
            anchor,
            page_rect,
            table_body_rows=table_body_rows,
            caption_anchors=anchors,
        )
        assets.append(
            {
                "asset_id": asset_id,
                "document_id": document_id,
                "page_number": page_number,
                "label": anchor["label"],
                "kind": kind,
                "caption_text": normalize_whitespace(anchor["line_text"]),
                "caption_detection": anchor["caption_detection"],
                "filename": filename,
                "path": str(output_path),
                "ext": "png",
                "width": int((bbox[2] - bbox[0]) * dpi / 72.0),
                "height": int((bbox[3] - bbox[1]) * dpi / 72.0),
                "bbox_pt": list(bbox),
                "bbox_sha256": crop_hash,
                "file_sha256": content_hash,
                "size_bytes": len(png_bytes),
                "extraction_level": "figure",
                "identity_confidence": 1.0,
                "quality_signals": quality_signals,
            }
        )
    return assets


def main() -> None:
    args = parser().parse_args()
    record = legacy.ensure_record(args.input)
    pdf_path = Path(str(record.get("pdf_path", "")).strip()).expanduser()
    if not pdf_path.exists():
        raise SystemExit("extract_pdf_assets_v2.py requires a resolvable local PDF path.")
    if fitz is None:
        raise SystemExit("extract_pdf_assets_v2.py requires PyMuPDF (`fitz`).")
    pdf_path = pdf_path.resolve()
    paper_id, run_id, pdf_hash = _stable_run_identity(record, pdf_path)
    document_id, document_role = _resolve_document(record, pdf_path)
    asset_root = (
        Path(args.assets_dir).expanduser().resolve()
        if args.assets_dir
        else default_assets_dir(record)
    )
    images_dir = asset_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    page_records: list[dict[str, Any]] = []
    image_assets: list[dict[str, Any]] = []
    figure_assets: list[dict[str, Any]] = []
    doc = fitz.open(pdf_path)
    try:
        page_limit = len(doc) if args.max_pages <= 0 else min(len(doc), args.max_pages)
        for index in range(page_limit):
            page = doc[index]
            page_number = index + 1
            text = normalize_whitespace(page.get_text("text"))
            searchable_chars = len(text)
            extraction_method = "text" if searchable_chars >= args.min_searchable_chars else "none"
            ocr_text = ""
            if extraction_method == "none":
                ocr_text = legacy.ocr_page(page, args.ocr_dpi)
                if ocr_text:
                    extraction_method = "ocr"
            page_images = extract_page_images_v2(
                doc, page, page_number, images_dir, document_id=document_id
            )
            page_figures = extract_figure_regions_v2(
                page,
                page_number,
                images_dir,
                document_id=document_id,
                dpi=args.figure_dpi,
            )
            image_assets.extend(page_images)
            figure_assets.extend(page_figures)
            page_records.append(
                {
                    "document_id": document_id,
                    "page_number": page_number,
                    "searchable_text_chars": searchable_chars,
                    "text_extraction_method": extraction_method,
                    "ocr_used": extraction_method == "ocr",
                    "image_count": len(page_images),
                    "figure_count": len(page_figures),
                    "page_text": text or ocr_text,
                    "text_preview": (text or ocr_text)[:240],
                }
            )
    finally:
        doc.close()

    manifest = make_figure_manifest(
        paper_id=paper_id,
        run_id=run_id,
        assets=figure_assets,
        failures=[],
    )
    payload = {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "status": "ok",
        "failures": [],
        "script": "extract_pdf_assets_v2.py",
        "paper_id": paper_id,
        "run_id": run_id,
        "document_id": document_id,
        "document_role": document_role,
        "pdf_path": str(pdf_path),
        "pdf_sha256": pdf_hash,
        "asset_root": str(asset_root),
        "images_dir": str(images_dir),
        "page_assets": page_records,
        "image_assets": image_assets,
        "figure_assets": figure_assets,
        "figure_manifest": manifest,
        "ocr_available": bool(legacy.pytesseract and legacy.Image),
    }
    emit(payload, args.output)


if __name__ == "__main__":
    main()

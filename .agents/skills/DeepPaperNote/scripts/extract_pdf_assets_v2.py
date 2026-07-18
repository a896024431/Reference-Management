#!/usr/bin/env python3
"""Extract canonical multi-document schema-v2 PDF visual assets.

This module reuses mature crop and visual-quality heuristics from the private core
extractor while fixing its identity and caption-detection failure modes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pdf_assets_core as core
from common import fitz, normalize_whitespace
from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    validate_paper_record_artifact,
)
from figure_contracts import build_figure_asset_identity, sha256_bytes, sha256_file
from figure_contracts_v2 import make_figure_manifest

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
    p = argparse.ArgumentParser(description=__doc__ or "extract pdf assets contract v2")
    p.add_argument("--input", required=True, help="paper_record v2 JSON.")
    p.add_argument("--output", default="")
    p.add_argument("--assets-dir", required=True, help="Run-local output directory.")
    p.add_argument(
        "--max-pages", type=int, default=0, help="Per-document limit; 0 scans all pages."
    )
    p.add_argument("--min-searchable-chars", type=int, default=100)
    p.add_argument("--ocr-dpi", type=int, default=300)
    p.add_argument("--figure-dpi", type=int, default=core.FIGURE_RENDER_DPI)
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
        "kind": core._classify_caption_kind(label),
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
                if core._looks_like_data_row(continuation_text):
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
        core.save_image_bytes(output_path, image_bytes)
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
    dpi: int = core.FIGURE_RENDER_DPI,
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
            table_result = core._estimate_table_bbox_with_rows(
                page, anchor, previous, following, page_rect
            )
            if table_result is not None:
                bbox, table_body_rows = table_result
            if bbox is None:
                bbox = core._estimate_figure_bbox_above_caption(page, anchor, previous, page_rect)
        else:
            bbox = core._estimate_figure_bbox_above_caption(page, anchor, previous, page_rect)
            if bbox is None:
                bbox = core._estimate_table_bbox(page, anchor, previous, following, page_rect)
        if bbox is None:
            continue
        try:
            png_bytes = core._render_crop(page, bbox, dpi)
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
        core.save_image_bytes(output_path, png_bytes)
        quality_signals = core._quality_signals_for_crop(
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


def extract_paper_record_assets(
    paper_record_artifact: dict[str, Any],
    *,
    assets_dir: str | Path,
    max_pages: int = 0,
    min_searchable_chars: int = 100,
    ocr_dpi: int = 300,
    figure_dpi: int = core.FIGURE_RENDER_DPI,
) -> dict[str, Any]:
    validate_paper_record_artifact(paper_record_artifact)
    if core.fitz is None:
        raise RuntimeError("PyMuPDF (`fitz`) is required")
    paper_id = str(paper_record_artifact["paper_id"])
    run_id = str(paper_record_artifact["run_id"])
    root = Path(assets_dir).expanduser().resolve()
    images_dir = root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    page_assets: list[dict[str, Any]] = []
    image_assets: list[dict[str, Any]] = []
    figure_assets: list[dict[str, Any]] = []
    failures: list[str] = []
    processed_documents: list[dict[str, Any]] = []

    documents = paper_record_artifact["paper_record"].get("documents", [])
    for document in documents:
        document_id = str(document.get("document_id", ""))
        document_role = str(document.get("role", ""))
        pdf_path = Path(str(document.get("path", ""))).expanduser()
        if not pdf_path.is_file():
            failures.append(f"pdf_asset_document_missing:{document_id}")
            continue
        doc = core.fitz.open(pdf_path.resolve())
        document_page_count = 0
        try:
            page_limit = len(doc) if max_pages <= 0 else min(len(doc), max_pages)
            for index in range(page_limit):
                page = doc[index]
                page_number = index + 1
                text = core.normalize_whitespace(page.get_text("text"))
                searchable_chars = len(text)
                extraction_method = "text" if searchable_chars >= min_searchable_chars else "none"
                ocr_text = ""
                if extraction_method == "none":
                    ocr_text = core.ocr_page(page, ocr_dpi)
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
                    dpi=figure_dpi,
                )
                image_assets.extend(page_images)
                figure_assets.extend(page_figures)
                page_assets.append(
                    {
                        "document_id": document_id,
                        "document_role": document_role,
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
                document_page_count += 1
        except Exception as exc:
            failures.append(f"pdf_asset_extraction_failed:{document_id}:{exc}")
        finally:
            doc.close()
        processed_documents.append(
            {
                "document_id": document_id,
                "role": document_role,
                "source_sha256": str(document.get("sha256", "")),
                "pages_processed": document_page_count,
            }
        )

    if not processed_documents:
        status = "fail"
    elif failures:
        status = "degraded"
    else:
        status = "pass"
    payload = artifact_header(
        "pdf_assets", paper_id=paper_id, run_id=run_id, status=status, failures=failures
    )
    payload.update(
        {
            "asset_root": str(root),
            "images_dir": str(images_dir),
            "documents": processed_documents,
            "page_assets": page_assets,
            "image_assets": image_assets,
            "figure_assets": figure_assets,
            "figure_manifest": make_figure_manifest(
                paper_id=paper_id,
                run_id=run_id,
                assets=figure_assets,
                failures=failures,
                status=status,
            ),
            "ocr_available": bool(core.pytesseract and core.Image),
        }
    )
    require_same_identity(payload, payload["figure_manifest"])
    return payload


def main() -> None:
    args = parser().parse_args()
    paper_record = load_json_object(args.input)
    payload = extract_paper_record_assets(
        paper_record,
        assets_dir=args.assets_dir,
        max_pages=args.max_pages,
        min_searchable_chars=args.min_searchable_chars,
        ocr_dpi=args.ocr_dpi,
        figure_dpi=args.figure_dpi,
    )
    emit_json(payload, args.output)


if __name__ == "__main__":
    main()

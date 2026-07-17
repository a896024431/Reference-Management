#!/usr/bin/env python3
"""Canonical multi-document PDF-assets entrypoint for paper_record v2."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import extract_pdf_assets as legacy
from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    validate_paper_record_artifact,
)
from extract_pdf_assets_v2 import extract_figure_regions_v2, extract_page_images_v2
from figure_contracts_v2 import make_figure_manifest


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
    p.add_argument("--figure-dpi", type=int, default=legacy.FIGURE_RENDER_DPI)
    return p


def extract_paper_record_assets(
    paper_record_artifact: dict[str, Any],
    *,
    assets_dir: str | Path,
    max_pages: int = 0,
    min_searchable_chars: int = 100,
    ocr_dpi: int = 300,
    figure_dpi: int = legacy.FIGURE_RENDER_DPI,
) -> dict[str, Any]:
    validate_paper_record_artifact(paper_record_artifact)
    if legacy.fitz is None:
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
        doc = legacy.fitz.open(pdf_path.resolve())
        document_page_count = 0
        try:
            page_limit = len(doc) if max_pages <= 0 else min(len(doc), max_pages)
            for index in range(page_limit):
                page = doc[index]
                page_number = index + 1
                text = legacy.normalize_whitespace(page.get_text("text"))
                searchable_chars = len(text)
                extraction_method = "text" if searchable_chars >= min_searchable_chars else "none"
                ocr_text = ""
                if extraction_method == "none":
                    ocr_text = legacy.ocr_page(page, ocr_dpi)
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
            "ocr_available": bool(legacy.pytesseract and legacy.Image),
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

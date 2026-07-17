#!/usr/bin/env python3
"""Rank figure candidates and emit schema-v2 figure decisions.

The planner is placeholder-first.  It recommends the best non-rejected asset,
but only a later semantic review may change a decision to ``inserted``.
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from common import emit, maybe_load_json_record, normalize_whitespace
from figure_contracts import (
    FIGURE_SCHEMA_VERSION,
    ensure_asset_identity,
    make_figure_manifest,
    normalize_figure_label,
    sha256_bytes,
)

STOPWORDS = {
    "and",
    "figure",
    "for",
    "from",
    "result",
    "results",
    "shows",
    "showing",
    "study",
    "table",
    "that",
    "the",
    "this",
    "with",
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "plan figures v2")
    p.add_argument("--input", default="", help="Primary JSON path or string.")
    p.add_argument("--evidence", default="", help="Evidence JSON path or string.")
    p.add_argument("--assets", default="", help="PDF assets JSON path or string.")
    p.add_argument("--output", default="", help="Output JSON path.")
    p.add_argument("--paper-id", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--max-items", type=int, default=12, help="0 keeps all items.")
    return p


def merge_inputs(
    primary: dict | None, evidence: dict | None, assets: dict | None
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in (primary, evidence, assets):
        if isinstance(value, dict):
            merged.update(value)
    if isinstance(evidence, dict) and isinstance(evidence.get("evidence_pack"), dict):
        merged["evidence_pack"] = evidence["evidence_pack"]
    if isinstance(assets, dict):
        for key in ("page_assets", "image_assets", "figure_assets", "figure_manifest"):
            if key in assets:
                merged[key] = assets[key]
    return merged


def _caption_keywords(caption: str, *, limit: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", caption.lower())
    picked: list[str] = []
    for word in words:
        if word in STOPWORDS or word in picked:
            continue
        picked.append(word)
        if len(picked) >= limit:
            break
    return picked


def _classify_caption(item_id: str, caption: str) -> tuple[str, str, str, int]:
    text = f"{item_id} {caption}".lower()
    if any(
        token in text
        for token in (
            "apparatus",
            "architecture",
            "device",
            "fabrication",
            "geometry",
            "measurement",
            "overview",
            "pipeline",
            "schematic",
            "setup",
            "workflow",
        )
    ):
        return (
            "method_overview",
            "实验体系与测量",
            "该图直接说明实验装置、器件结构或测量链，适合用于建立证据链的起点。",
            1,
        )
    if any(
        token in text
        for token in (
            "comparison",
            "conductance",
            "current",
            "dependence",
            "distribution",
            "performance",
            "phase",
            "resistance",
            "result",
            "spectrum",
            "temperature",
            "voltage",
        )
    ):
        return (
            "main_result",
            "主要结果和证据",
            "该图承载关键观测或定量比较，应与正文中的核心结论和来源锚点放在一起。",
            2,
        )
    if normalize_figure_label(item_id).startswith("table"):
        return (
            "table_result",
            "主要结果和证据",
            "该表汇总关键参数或比较结果，适合用于核对正文中的定量判断。",
            2,
        )
    return (
        "supporting_figure",
        "物理解释与替代解释",
        "该图提供补充证据；是否插入取决于它对主要论证是否不可替代。",
        3,
    )


def build_figure_items(evidence_pack: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    raw_items: list[dict[str, Any]] = []
    for source_key, source_kind in (("figure_captions", "figure"), ("table_captions", "table")):
        for value in evidence_pack.get(source_key, []) or []:
            if not isinstance(value, dict):
                continue
            raw_items.append(
                {
                    "id": normalize_whitespace(str(value.get("id", "") or value.get("label", ""))),
                    "caption": normalize_whitespace(
                        str(value.get("caption", "") or value.get("caption_text", ""))
                    ),
                    "source": source_kind,
                    "document_id": str(value.get("document_id", "") or "main"),
                    "page_number": int(value.get("page_number", 0) or 0),
                }
            )
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in raw_items:
        if not item["id"]:
            continue
        key = f"{item['document_id']}|{normalize_figure_label(item['id'])}"
        current = grouped.get(key)
        if current is None:
            grouped[key] = item
            order.append(key)
        elif len(item["caption"]) > len(current.get("caption", "")):
            grouped[key] = item
    planned: list[dict[str, Any]] = []
    for key in order:
        item = grouped[key]
        kind, section, reason, priority = _classify_caption(item["id"], item["caption"])
        planned.append(
            {
                "target_id": key,
                "id": item["id"],
                "caption": item["caption"],
                "document_id": item["document_id"],
                "page_number": item["page_number"],
                "kind": kind,
                "section": section,
                "reason": reason,
                "priority": priority,
                "anchor_text": section,
                "insert_mode": "placeholder",
            }
        )
    planned.sort(
        key=lambda item: (item["priority"], item["document_id"], normalize_figure_label(item["id"]))
    )
    return planned if limit <= 0 else planned[:limit]


def _quality_status(asset: dict[str, Any]) -> str:
    signals = asset.get("quality_signals")
    return str(signals.get("visual_quality_status", "")) if isinstance(signals, dict) else ""


def _candidate_status(asset: dict[str, Any]) -> str:
    quality = _quality_status(asset)
    if quality == "usable":
        return "usable_candidate"
    if quality == "reject":
        return "reject_visual_quality"
    return "needs_visual_quality_check"


def _caption_similarity(left: str, right: str) -> float:
    left_words = set(_caption_keywords(left, limit=24))
    right_words = set(_caption_keywords(right, limit=24))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def _candidate_score(item: dict[str, Any], asset: dict[str, Any]) -> float:
    if _quality_status(asset) == "reject":
        return -10000.0
    score = 0.0
    if normalize_figure_label(str(item.get("id", ""))) == normalize_figure_label(
        str(asset.get("label", ""))
    ):
        score += 50.0
    if str(item.get("document_id", "") or "main") == str(asset.get("document_id", "") or "main"):
        score += 25.0
    quality = _quality_status(asset)
    score += 100.0 if quality == "usable" else 35.0
    similarity = _caption_similarity(
        str(item.get("caption", "")), str(asset.get("caption_text", ""))
    )
    score += similarity * 30.0
    signals = asset.get("quality_signals", {})
    if isinstance(signals, dict):
        score += min(float(signals.get("visual_body_ratio", 0.0) or 0.0), 1.0) * 15.0
        score -= min(float(signals.get("page_coverage_ratio", 0.0) or 0.0), 1.0) * 2.0
    if int(asset.get("width", 0) or 0) >= 480 and int(asset.get("height", 0) or 0) >= 240:
        score += 5.0
    return round(score, 6)


def _asset_candidate(item: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    normalized = ensure_asset_identity(
        asset, document_id=str(item.get("document_id", "") or "main")
    )
    return {
        "asset_id": normalized.get("asset_id", ""),
        "document_id": normalized.get("document_id", ""),
        "page_number": int(normalized.get("page_number", 0) or 0),
        "filename": normalized.get("filename", ""),
        "path": normalized.get("path", ""),
        "file_sha256": normalized.get("file_sha256", ""),
        "width": normalized.get("width", 0),
        "height": normalized.get("height", 0),
        "size_bytes": normalized.get("size_bytes", 0),
        "label": normalized.get("label", ""),
        "caption_text": normalized.get("caption_text", ""),
        "extraction_level": normalized.get("extraction_level", "figure"),
        "quality_signals": normalized.get("quality_signals", {}),
        "candidate_status": _candidate_status(normalized),
        "identity_confidence": 1.0
        if normalize_figure_label(str(item.get("id", "")))
        == normalize_figure_label(str(normalized.get("label", "")))
        else 0.0,
        "caption_similarity": round(
            _caption_similarity(
                str(item.get("caption", "")), str(normalized.get("caption_text", ""))
            ),
            6,
        ),
        "ranking_score": _candidate_score(item, normalized),
    }


def rank_matching_assets(
    item: dict[str, Any], assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    target_label = normalize_figure_label(str(item.get("id", "")))
    target_document = str(item.get("document_id", "") or "main")
    matched: list[dict[str, Any]] = []
    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        asset = ensure_asset_identity(raw_asset, document_id=target_document)
        if normalize_figure_label(str(asset.get("label", ""))) != target_label:
            continue
        if str(asset.get("document_id", "") or "main") != target_document:
            continue
        matched.append(_asset_candidate(item, asset))
    matched.sort(
        key=lambda candidate: (
            candidate["candidate_status"] == "reject_visual_quality",
            -float(candidate["ranking_score"]),
            int(candidate["page_number"]),
            str(candidate["asset_id"]),
        )
    )
    return matched


def _match_snippet(page_text: str, needle: str, *, radius: int = 90) -> str:
    index = page_text.lower().find(needle.lower())
    if index < 0:
        return ""
    return normalize_whitespace(page_text[max(0, index - radius) : index + len(needle) + radius])[
        :220
    ]


def attach_candidate_images(
    items: list[dict[str, Any]],
    page_assets: list[dict[str, Any]],
    image_assets: list[dict[str, Any]],
    figure_assets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    figures = [asset for asset in (figure_assets or []) if isinstance(asset, dict)]
    image_map: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for image in image_assets:
        if not isinstance(image, dict):
            continue
        key = (str(image.get("document_id", "") or "main"), int(image.get("page_number", 0) or 0))
        image_map.setdefault(key, []).append(image)
    pages = [page for page in page_assets if isinstance(page, dict)]

    for index, item in enumerate(items):
        ranked = rank_matching_assets(item, figures)
        usable = [
            candidate
            for candidate in ranked
            if candidate["candidate_status"] != "reject_visual_quality"
        ]
        rejected = [
            candidate
            for candidate in ranked
            if candidate["candidate_status"] == "reject_visual_quality"
        ]
        item["figure_asset_candidates"] = ranked
        item["rejected_asset_ids"] = [candidate["asset_id"] for candidate in rejected]
        if usable:
            item["figure_asset_candidate"] = usable[0]
            item["recommended_asset_id"] = usable[0]["asset_id"]
            item["candidate_status"] = usable[0]["candidate_status"]
        else:
            item["recommended_asset_id"] = ""
            item["candidate_status"] = "no_insertable_candidate"

        document_id = str(item.get("document_id", "") or "main")
        label = normalize_figure_label(str(item.get("id", "")))
        keywords = _caption_keywords(str(item.get("caption", "")))
        candidates: list[dict[str, Any]] = []
        for page in pages:
            page_document = str(page.get("document_id", "") or "main")
            if page_document != document_id:
                continue
            page_number = int(page.get("page_number", 0) or 0)
            page_text = normalize_whitespace(str(page.get("page_text", "")))
            page_figure_candidates = [
                candidate
                for candidate in ranked
                if int(candidate.get("page_number", 0) or 0) == page_number
            ]
            score = 12 if page_figure_candidates else 0
            matched_terms: list[str] = []
            snippet = ""
            if label and label in normalize_figure_label(page_text):
                score += 5
                matched_terms.append(label)
                snippet = _match_snippet(page_text, str(item.get("id", "")))
            keyword_hits = [word for word in keywords if word in page_text.lower()]
            score += min(len(keyword_hits), 3)
            matched_terms.extend(keyword_hits[:3])
            if score == 0 and index < len(pages) and pages[index] is page:
                score = 1
                matched_terms.append("order_fallback")
            if score <= 0:
                continue
            candidates.append(
                {
                    "document_id": document_id,
                    "page_number": page_number,
                    "score": score,
                    "matched_terms": matched_terms,
                    "snippet": snippet
                    or normalize_whitespace(str(page.get("text_preview", "")))[:220],
                    "images": [
                        {
                            "asset_id": ensure_asset_identity(image, document_id=document_id).get(
                                "asset_id", ""
                            ),
                            "filename": image.get("filename", ""),
                            "path": image.get("path", ""),
                            "width": image.get("width", 0),
                            "height": image.get("height", 0),
                            "size_bytes": image.get("size_bytes", 0),
                        }
                        for image in image_map.get((document_id, page_number), [])[:3]
                    ],
                    "figure_assets": page_figure_candidates,
                }
            )
        candidates.sort(key=lambda candidate: (-candidate["score"], candidate["page_number"]))
        item["candidate_pages"] = candidates[:3]
        item["matching_strategy"] = "quality-first-label-and-caption-ranking-v2"
    return items


def build_figure_decisions(
    *, paper_id: str, run_id: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for item in items:
        candidates = item.get("figure_asset_candidates", []) or []
        candidate_ids = [
            str(candidate.get("asset_id", ""))
            for candidate in candidates
            if candidate.get("candidate_status") != "reject_visual_quality"
            and candidate.get("asset_id")
        ]
        recommended = str(item.get("recommended_asset_id", ""))
        decisions.append(
            {
                "target_id": str(item.get("target_id", "") or item.get("id", "")),
                "display_label": str(item.get("id", "")),
                "caption": str(item.get("caption", "")),
                "document_id": str(item.get("document_id", "") or "main"),
                "target_section": str(item.get("section", "")),
                "priority": int(item.get("priority", 3) or 3),
                "reason": str(item.get("reason", "")),
                "decision": "placeholder",
                "selected_asset_id": "",
                "recommended_asset_id": recommended,
                "candidate_asset_ids": candidate_ids,
                "rejected_asset_ids": list(item.get("rejected_asset_ids", []) or []),
                "decision_reason": "awaiting_semantic_confirmation"
                if recommended
                else "no_visually_usable_matching_asset",
            }
        )
    return {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "paper_id": paper_id,
        "run_id": run_id,
        "status": "ok",
        "failures": [],
        "decisions": decisions,
    }


def _fallback_identity(data: dict[str, Any]) -> tuple[str, str]:
    seed = str(data.get("title", "") or data.get("pdf_path", "") or "unknown-paper")
    paper_id = str(data.get("paper_id", "") or f"paper-{sha256_bytes(seed.encode('utf-8'))[:16]}")
    run_id = str(
        data.get("run_id", "") or f"run-{paper_id}-{sha256_bytes(seed.encode('utf-8'))[:12]}"
    )
    return paper_id, run_id


def main() -> None:
    args = parser().parse_args()
    primary = maybe_load_json_record(args.input) if args.input else None
    evidence = maybe_load_json_record(args.evidence) if args.evidence else None
    assets_record = maybe_load_json_record(args.assets) if args.assets else None
    data = merge_inputs(primary, evidence, assets_record)
    if not data:
        raise SystemExit("plan_figures_v2.py requires at least one JSON input.")
    fallback_paper_id, fallback_run_id = _fallback_identity(data)
    paper_id = args.paper_id or fallback_paper_id
    run_id = args.run_id or fallback_run_id
    evidence_pack = (
        data.get("evidence_pack", {}) if isinstance(data.get("evidence_pack"), dict) else {}
    )
    page_assets = data.get("page_assets", []) if isinstance(data.get("page_assets"), list) else []
    image_assets = (
        data.get("image_assets", []) if isinstance(data.get("image_assets"), list) else []
    )
    manifest = (
        data.get("figure_manifest") if isinstance(data.get("figure_manifest"), dict) else None
    )
    if manifest is not None:
        figure_assets = [asset for asset in manifest.get("assets", []) if isinstance(asset, dict)]
        paper_id = args.paper_id or str(manifest.get("paper_id", "") or paper_id)
        run_id = args.run_id or str(manifest.get("run_id", "") or run_id)
    else:
        figure_assets = (
            data.get("figure_assets", []) if isinstance(data.get("figure_assets"), list) else []
        )
        manifest = make_figure_manifest(
            paper_id=paper_id,
            run_id=run_id,
            assets=figure_assets,
            status="degraded",
            failures=["legacy_figure_assets_without_manifest"],
        )
    items = build_figure_items(evidence_pack, limit=args.max_items)
    items = attach_candidate_images(items, page_assets, image_assets, figure_assets)
    decisions = build_figure_decisions(paper_id=paper_id, run_id=run_id, items=items)
    payload = {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "status": "ok",
        "failures": [],
        "script": "plan_figures_v2.py",
        "paper_id": paper_id,
        "run_id": run_id,
        "figure_manifest": manifest,
        "figure_plan": {"paper_id": paper_id, "run_id": run_id, "figures": items},
        "figure_decisions": decisions,
    }
    emit(payload, args.output)


if __name__ == "__main__":
    main()

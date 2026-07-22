#!/usr/bin/env python3
"""Plan current-run figure candidates and resolve the images a note actually embeds."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

from common import normalize_whitespace
from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_same_identity,
    require_v2_artifact,
)
from extract_pdf_assets_v2 import _parse_caption_start
from figure_contracts_v2 import (
    ensure_asset_identity,
    finalize_note_figure_decisions,
    make_figure_decisions,
    normalize_figure_decisions,
    normalize_figure_label,
    normalize_figure_manifest,
)

BRIDGE_SOURCE = "manifest_caption_bridge_v2"
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
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--evidence", default="")
    command.add_argument("--assets", default="")
    command.add_argument(
        "--finalize-note",
        default="",
        help="Internal mode: resolve image names embedded in this staged note.",
    )
    command.add_argument("--manifest", default="")
    command.add_argument("--decisions", default="")
    command.add_argument("--output", default="")
    command.add_argument("--max-items", type=int, default=0, help="0 keeps every target.")
    return command


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
                "decision": "omitted",
                "selected_asset_id": "",
                "recommended_asset_id": recommended,
                "candidate_asset_ids": candidate_ids,
                "rejected_asset_ids": list(item.get("rejected_asset_ids", []) or []),
                "decision_reason": "not_embedded",
            }
        )
    return make_figure_decisions(
        paper_id=paper_id,
        run_id=run_id,
        decisions=decisions,
        status="pass",
    )


def _bridge_identity(
    asset: dict[str, Any],
) -> tuple[str, str, int] | None:
    """Return a stable bridge identity only for a real usable caption crop."""
    if str(asset.get("caption_detection", "")) != "anchored_label_v2":
        return None
    if _quality_status(asset) != "usable":
        return None
    document_id = str(asset.get("document_id", "")).strip()
    page_number = int(asset.get("page_number", 0) or 0)
    label = normalize_figure_label(str(asset.get("label", "")))
    if not document_id or page_number <= 0 or not label:
        return None
    if not label.startswith(("fig ", "fig s", "table ", "extended data fig ")):
        return None
    parsed = _parse_caption_start(str(asset.get("caption_text", "")))
    if parsed is None:
        return None
    if normalize_figure_label(parsed["label"]) != label:
        return None
    return document_id, label, page_number


def _bridge_rank(asset: dict[str, Any]) -> tuple[float, float, int, str]:
    signals = asset.get("quality_signals", {})
    if not isinstance(signals, dict):
        signals = {}
    return (
        float(asset.get("identity_confidence", 0.0) or 0.0),
        float(signals.get("visual_body_ratio", 0.0) or 0.0),
        len(str(asset.get("caption_text", ""))),
        str(asset.get("asset_id", "")),
    )


def build_manifest_caption_bridge_items(
    existing_items: list[dict[str, Any]],
    manifest_assets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build missing intents without collapsing main and supplement labels."""
    existing_labels = {
        (
            str(item.get("document_id", "") or "main"),
            normalize_figure_label(str(item.get("id", ""))),
        )
        for item in existing_items
    }
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    counters: Counter[str] = Counter()
    for raw in manifest_assets:
        if not isinstance(raw, dict):
            counters["non_object"] += 1
            continue
        identity = _bridge_identity(raw)
        if identity is None:
            if _quality_status(raw) != "usable":
                counters["not_usable"] += 1
            elif str(raw.get("caption_detection", "")) != "anchored_label_v2":
                counters["not_anchored"] += 1
            else:
                counters["caption_start_rejected"] += 1
            continue
        document_id, label, _ = identity
        if (document_id, label) in existing_labels:
            counters["already_in_evidence"] += 1
            continue
        grouped.setdefault(identity, []).append(raw)

    bridge_items: list[dict[str, Any]] = []
    for (document_id, label, page_number), candidates in grouped.items():
        source = max(candidates, key=_bridge_rank)
        display_label = str(source.get("label", ""))
        caption = str(source.get("caption_text", "")).strip()
        kind, section, reason, priority = _classify_caption(display_label, caption)
        bridge_items.append(
            {
                "target_id": (f"{document_id}|{label}|p{page_number:04d}"),
                "id": display_label,
                "caption": caption,
                "document_id": document_id,
                "page_number": page_number,
                "kind": kind,
                "section": section,
                "reason": reason,
                "priority": priority,
                "anchor_text": section,
                "intent_source": BRIDGE_SOURCE,
                "source_asset_id": str(source.get("asset_id", "")),
            }
        )
    bridge_items.sort(
        key=lambda item: (
            int(item["priority"]),
            str(item["document_id"]),
            int(item["page_number"]),
            normalize_figure_label(str(item["id"])),
        )
    )
    counters["created"] = len(bridge_items)
    return bridge_items, dict(counters)


def _stabilize_bridged_candidates(items: list[dict[str, Any]]) -> None:
    """Keep bridged recommendations on the source document and page."""
    for item in items:
        if item.get("intent_source") != BRIDGE_SOURCE:
            continue
        source_page = int(item.get("page_number", 0) or 0)
        candidates = [
            candidate
            for candidate in item.get("figure_asset_candidates", [])
            if int(candidate.get("page_number", 0) or 0) == source_page
        ]
        usable = [
            candidate
            for candidate in candidates
            if candidate.get("candidate_status") == "usable_candidate"
        ]
        rejected = [
            candidate
            for candidate in candidates
            if candidate.get("candidate_status") == "reject_visual_quality"
        ]
        item["figure_asset_candidates"] = candidates
        item["rejected_asset_ids"] = [str(candidate.get("asset_id", "")) for candidate in rejected]
        if usable:
            item["figure_asset_candidate"] = usable[0]
            item["recommended_asset_id"] = str(usable[0].get("asset_id", ""))
            item["candidate_status"] = "usable_candidate"
        else:
            item.pop("figure_asset_candidate", None)
            item["recommended_asset_id"] = ""
            item["candidate_status"] = "no_insertable_candidate"


def build_release_figure_plan_artifact(
    evidence_artifact: dict[str, Any],
    assets_artifact: dict[str, Any],
    *,
    max_items: int = 0,
) -> dict[str, Any]:
    require_v2_artifact(evidence_artifact, artifact_type="evidence_pack")
    require_v2_artifact(assets_artifact, artifact_type="pdf_assets")
    paper_id, run_id = require_same_identity(evidence_artifact, assets_artifact)
    manifest = normalize_figure_manifest(assets_artifact)
    pack = evidence_artifact.get("evidence_pack", {})
    if not isinstance(pack, dict):
        pack = {}
    evidence_items = build_figure_items(pack, limit=0)
    bridge_items, bridge_summary = build_manifest_caption_bridge_items(
        evidence_items,
        [asset for asset in manifest.get("assets", []) if isinstance(asset, dict)],
    )
    items = evidence_items + bridge_items
    items.sort(
        key=lambda item: (
            int(item.get("priority", 3) or 3),
            str(item.get("document_id", "")),
            int(item.get("page_number", 0) or 0),
            normalize_figure_label(str(item.get("id", ""))),
        )
    )
    if max_items > 0:
        items = items[:max_items]
    items = attach_candidate_images(
        items,
        assets_artifact.get("page_assets", []),
        assets_artifact.get("image_assets", []),
        manifest.get("assets", []),
    )
    _stabilize_bridged_candidates(items)
    raw_decisions = build_figure_decisions(paper_id=paper_id, run_id=run_id, items=items)
    decisions = normalize_figure_decisions(raw_decisions, manifest=manifest, require_final=False)
    artifact = artifact_header("figure_plan", paper_id=paper_id, run_id=run_id, status="pass")
    artifact.update(
        {
            "planner": "plan_figures_v2.py",
            "figure_plan": {
                "paper_id": paper_id,
                "run_id": run_id,
                "figures": items,
            },
            "figure_manifest": manifest,
            "figure_decisions": decisions,
            "caption_bridge": {
                "source": BRIDGE_SOURCE,
                "evidence_targets": len(evidence_items),
                **bridge_summary,
            },
        }
    )
    return artifact


def main() -> None:
    args = parser().parse_args()
    if args.finalize_note:
        if not args.manifest or not args.decisions:
            raise SystemExit("--finalize-note requires --manifest and --decisions")
        from vault import paper_local_image_names

        try:
            note_text = Path(args.finalize_note).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"Cannot read staged note: {exc}") from exc
        names, failures = paper_local_image_names(note_text)
        if failures:
            raise SystemExit("Staged note image references are invalid: " + "; ".join(failures))
        try:
            artifact = finalize_note_figure_decisions(
                manifest=load_json_object(args.manifest),
                provisional_decisions=load_json_object(args.decisions),
                embedded_filenames=names,
            )
        except Exception as exc:
            raise SystemExit(str(exc)) from exc
    else:
        if not args.evidence or not args.assets:
            raise SystemExit("Planning requires --evidence and --assets")
        artifact = build_release_figure_plan_artifact(
            load_json_object(args.evidence),
            load_json_object(args.assets),
            max_items=args.max_items,
        )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

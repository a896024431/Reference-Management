#!/usr/bin/env python3
"""Lint the final reader-visible DeepPaperNote schema-v2 note."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from contracts_v2 import (
    artifact_header,
    emit_json,
    load_json_object,
    require_v2_artifact,
    sha256_text,
)
from note_lint_core import (
    math_render_issues,
    mixed_language_issues,
    suspicious_code_formatted_math,
    suspicious_mid_sentence_linebreaks,
)
from vault import parse_frontmatter, validate_frontmatter_properties

REQUIRED_HEADINGS = (
    "30 秒速览",
    "关键结论",
    "适用边界",
    "快速入口与页面导航",
    "原文摘要翻译",
    "创新点",
    "研究问题",
    "主要结果与证据链",
    "解释、替代解释与证据边界",
    "局限与未决问题",
    "可复用结论",
    "相关论文",
    "我的笔记",
    "引用",
)
REQUIRED_HEADING_ALIASES: dict[str, tuple[str, ...]] = {
    "主要结果与证据链": ("主要结果与证据链", "主要结果"),
    "解释、替代解释与证据边界": (
        "解释、替代解释与证据边界",
        "如何理解这些结果",
    ),
}
METHOD_HEADINGS = {
    "实验设计与分析方法",
    "实验体系、方法或理论模型",
    "实验体系或理论模型",
    "方法与测量／推断链",
    "方法与测量/推断链",
    "实验体系与测量",
    "理论模型",
    "材料与工艺",
    "方法主线",
}
AI_LEAKAGE = (
    "不是机器学习任务",
    "不是数值预测任务",
    "输入是",
    "操作是",
    "输出是",
)
# Figure extraction, ranking, and visual QA are run artifacts. They explain why
# the pipeline made a decision, but they are not part of a reader-facing note.
# Keep these patterns deliberately narrow: an ordinary discussion of a hash
# function, for example, is not a failure unless it is clearly figure QA text.
READER_VISIBLE_FIGURE_METADATA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "figure_placeholder_callout_present",
        re.compile(r"(?im)^\s*>\s*\[!figure(?:[^\]]*)\]"),
    ),
    (
        "figure_planning_label_present",
        re.compile(
            r"(?im)^\s*(?:>\s*)?(?:"
            r"建议位置|放置原因|当前状态|"
            r"suggested(?:\s+figure)?\s+location|placement\s+reason|"
            r"why\s+here|current\s+status"
            r")\s*[:：]"
        ),
    ),
    (
        "source_figure_target_id_present",
        re.compile(r"(?i)\bdoc:[A-Za-z0-9._-]+\|(?:fig(?:ure)?|table)\b"),
    ),
    (
        "figure_qa_metadata_present",
        re.compile(
            r"(?i)(?:"
            r"图号(?:身份|匹配|识别)|面板完整性|裁剪完整度|"
            r"(?:图像|图片|插图|图表|裁剪|资源).{0,18}"
            r"(?:哈希|sha-?256|asset[_ -]?id|bbox[_ -]?hash)|"
            r"(?:哈希|sha-?256|asset[_ -]?id|bbox[_ -]?hash).{0,18}"
            r"(?:图像|图片|插图|图表|裁剪|资源|一致性|校验|核验|匹配)|"
            r"(?:候选|裁剪|资源).{0,18}(?:身份|完整性|可读性|复核|核验|校验)|"
            r"(?:图例|坐标).{0,18}(?:可读性)?(?:复核|核验|校验)|"
            r"\b(?:selected_asset_id|candidate_asset_ids|rejected_asset_ids|asset_id|bbox_hash|file_sha256|decision_reason|target_section)\b|"
            r"\b(?:reject(?:_visual_quality)?|visual[_ -]?quality(?:_status)?)\b"
            r")"
        ),
    ),
    (
        "figure_process_metadata_present",
        re.compile(
            r"(?i)(?:"
            r"\b(?:candidate(?:\s+(?:image|asset|crop))?|crop(?:ped)?|contact\s+sheet|qa|materialize(?:d|ation)?|quality\s+gate|publication\s+gate)\b|"
            r"候选(?:图|图片|资源)|(?:图像|图片|插图|图表).{0,16}(?:裁剪|候选|物化|复核|质检|门禁)|"
            r"(?:已|已经|尚未|未).{0,12}(?:插入|提取|裁剪|物化)"
            r")"
        ),
    ),
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True)
    command.add_argument("--context", required=True, help="v2 synthesis bundle or paper record")
    command.add_argument("--output", default="")
    return command


def _paper_type(context: dict[str, Any]) -> str:
    if context.get("artifact_type") == "synthesis_bundle":
        return str(context.get("paper_type", "generic"))
    record = context.get("paper_record", {})
    metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
    return str(metadata.get("paper_type", "generic"))


def _section(body: str, title: str) -> str:
    match = re.search(
        rf"(?ms)^##\s+{re.escape(title)}\s*$\n(.*?)(?=^##\s+|\Z)",
        body,
    )
    return match.group(1) if match else ""


SOURCE_ANCHOR_RE = re.compile(
    r"(?:主文|补充材料)\s*(?:p{1,2}\.\s*\d+(?:\s*[-–—]\s*\d+)?|第\s*\d+(?:\s*[-–—]\s*\d+)?\s*页)"
)
LATEX_COMMAND_RE = re.compile(
    r"(?<!\\)\\(?:alpha|beta|gamma|delta|epsilon|theta|lambda|mu|nu|xi|pi|rho|"
    r"sigma|tau|phi|chi|psi|omega|frac|sqrt|sum|prod|int|mathcal|mathrm|mathbf|"
    r"text|begin|end|left|right|cdot|times|pm|le|ge|approx)\b"
)


def _mask_match(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def latex_commands_outside_math(text: str) -> list[dict[str, object]]:
    visible = parse_frontmatter(text).body
    for pattern, flags in (
        (r"```.*?```", re.DOTALL),
        (r"`[^`\n]*`", 0),
        (r"\\\[.*?\\\]", re.DOTALL),
        (r"\\\(.*?\\\)", re.DOTALL),
        (r"\$\$.*?\$\$", re.DOTALL),
        (r"(?<!\\)\$(?:\\.|[^$\n])*?(?<!\\)\$", 0),
    ):
        visible = re.sub(pattern, _mask_match, visible, flags=flags)
    issues: list[dict[str, object]] = []
    for match in LATEX_COMMAND_RE.finditer(visible):
        issues.append(
            {
                "line": visible.count("\n", 0, match.start()) + 1,
                "command": match.group(0),
            }
        )
    return issues


def _claim_items(section: str) -> list[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(
            r"(?ms)^\s*[-*]\s+(.+?)(?=^\s*[-*]\s+|\Z)",
            section,
        )
    ]


def _reader_visible_body(text: str) -> str:
    """Remove machine-only markup before checking reader-visible figure prose."""
    body = parse_frontmatter(text).body
    # Asset filenames contain identifiers and hashes by design; an image embed is
    # not reader-visible QA prose, so do not let it trigger the metadata gate.
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    body = re.sub(r"!\[\[[^\]]+\]\]", "", body)
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    return body


def reader_visible_figure_metadata_issues(text: str) -> list[dict[str, object]]:
    """Find planning/QA metadata that must never appear in a published note."""
    source_body = parse_frontmatter(text).body
    issues: list[dict[str, object]] = []
    for match in re.finditer(r"<!--.*?-->", source_body, flags=re.DOTALL):
        line = source_body.count("\n", 0, match.start()) + 1
        issues.append(
            {
                "code": "published_html_comment_present",
                "line": line,
                "excerpt": match.group(0).strip().replace("\n", " ")[:160],
            }
        )
    body = _reader_visible_body(text)
    for code, pattern in READER_VISIBLE_FIGURE_METADATA_PATTERNS:
        for match in pattern.finditer(body):
            line = body.count("\n", 0, match.start()) + 1
            excerpt = match.group(0).strip().replace("\n", " ")
            issues.append({"code": code, "line": line, "excerpt": excerpt[:160]})
    return issues


def build_release_lint(
    text: str, context: dict[str, Any], *, input_path: str = ""
) -> dict[str, Any]:
    require_v2_artifact(context, artifact_type={"synthesis_bundle", "paper_record"})
    parsed = parse_frontmatter(text)
    failures = list(parsed.errors)
    frontmatter_issues = validate_frontmatter_properties(parsed.properties)
    failures.extend(f"frontmatter:{item['code']}:{item['property']}" for item in frontmatter_issues)
    body = parsed.body
    h1_headings = re.findall(r"(?m)^#\s+(.+?)\s*$", body)
    if not h1_headings:
        failures.append("title_heading_missing")
    elif len(h1_headings) > 1:
        failures.append("multiple_h1_headings")
    english_title_lines = re.findall(
        r"(?m)^\*([A-Za-z][^*\n]{15,})\*\s*$",
        body,
    )
    normalized_english_titles = [
        re.sub(r"\W+", " ", item).strip().casefold() for item in english_title_lines
    ]
    if len(normalized_english_titles) != len(set(normalized_english_titles)):
        failures.append("duplicate_english_title")
    headings = re.findall(r"(?m)^##\s+(.+?)\s*$", body)
    heading_targets = {
        match.group(1).strip() for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", body)
    }
    broken_internal_heading_links: list[dict[str, object]] = []
    for match in re.finditer(r"(?<!!)\[\[#([^|\]]+)(?:\|[^\]]*)?\]\]", body):
        target = match.group(1).strip()
        if target not in heading_targets:
            broken_internal_heading_links.append(
                {
                    "line": body.count("\n", 0, match.start()) + 1,
                    "target": target,
                }
            )
    failures.extend(
        f"internal_heading_link_missing:{item['target']}" for item in broken_internal_heading_links
    )
    for title in REQUIRED_HEADINGS:
        accepted = REQUIRED_HEADING_ALIASES.get(title, (title,))
        if not any(candidate in headings for candidate in accepted):
            failures.append(f"required_section_missing:{title}")
    if not METHOD_HEADINGS.intersection(headings):
        failures.append("domain_method_section_missing")

    claims = _section(body, "关键结论")
    claim_items = _claim_items(claims)
    claim_count = len(claim_items)
    if claim_count < 3:
        failures.append("fewer_than_three_key_claims")
    unanchored_claims = [
        index
        for index, claim in enumerate(claim_items, start=1)
        if not SOURCE_ANCHOR_RE.search(claim)
    ]
    failures.extend(f"key_claim_missing_source_anchor:{index}" for index in unanchored_claims)
    anchors = SOURCE_ANCHOR_RE.findall(body)
    if len(anchors) < 3:
        failures.append("fewer_than_three_source_anchors")

    expected_type = _paper_type(context)
    actual_type = str(parsed.properties.get("paper_type", ""))
    legacy_generic_record = (
        context.get("artifact_type") == "paper_record" and expected_type == "generic"
    )
    if actual_type and expected_type and actual_type != expected_type and not legacy_generic_record:
        failures.append(f"paper_type_mismatch:{actual_type}:{expected_type}")
    if expected_type != "ai_method":
        leaked = [phrase for phrase in AI_LEAKAGE if phrase in body]
        if leaked:
            failures.append(f"ai_template_leakage:{','.join(leaked)}")
    if re.search(r"(?i)[A-Z]:\\Users\\|/Users/[^/]+/|/home/[^/]+/", text):
        failures.append("absolute_local_path_present")
    if re.search(r"(?i)Zotero\s+(?:not available|unavailable)", text):
        failures.append("runtime_status_persisted")
    if re.search(r"(?i)(?:^|[\s`'(])(?:\.local|tmp|DeepPaperNote_output)[/\\]", text):
        failures.append("temporary_path_present")

    mixed = mixed_language_issues(text)
    figure_metadata_issues = reader_visible_figure_metadata_issues(text)
    failures.extend(item["code"] for item in figure_metadata_issues)
    linebreaks = suspicious_mid_sentence_linebreaks(body)
    code_math = suspicious_code_formatted_math(text)
    math_issues = math_render_issues(text)
    raw_latex_issues = latex_commands_outside_math(text)
    if mixed:
        failures.append("mixed_language_lines_present")
    if linebreaks:
        failures.append("suspicious_mid_sentence_linebreaks")
    if code_math:
        failures.append("code_formatted_math_present")
    if math_issues:
        failures.append("math_render_issues_present")
    if raw_latex_issues:
        failures.append("latex_command_outside_math")
    failures = list(dict.fromkeys(failures))

    artifact = artifact_header(
        "lint_report",
        paper_id=str(context["paper_id"]),
        run_id=str(context["run_id"]),
        status="pass" if not failures else "fail",
        failures=failures,
    )
    artifact.update(
        {
            "input_path": input_path,
            "note_sha256": sha256_text(text),
            "h1_headings": h1_headings,
            "headings": headings,
            "english_title_lines": english_title_lines,
            "broken_internal_heading_links": broken_internal_heading_links,
            "key_claim_count": claim_count,
            "source_anchor_count": len(anchors),
            "frontmatter_issues": frontmatter_issues,
            "mixed_language_issues": mixed,
            "linebreak_issues": linebreaks,
            "code_math_issues": code_math,
            "math_render_issues": math_issues,
            "latex_commands_outside_math": raw_latex_issues,
            "unanchored_key_claims": unanchored_claims,
            "reader_visible_figure_metadata_issues": figure_metadata_issues,
            "passes_basic_structure": not any(
                item.startswith(
                    (
                        "frontmatter",
                        "required_section",
                        "title_heading",
                        "multiple_h1",
                        "domain_method",
                        "internal_heading_link",
                    )
                )
                for item in failures
            ),
            "passes_style_gate": not any(
                item in failures
                for item in (
                    "mixed_language_lines_present",
                    "suspicious_mid_sentence_linebreaks",
                    "code_formatted_math_present",
                )
            ),
            "passes_math_gate": not any(
                item in failures
                for item in ("math_render_issues_present", "latex_command_outside_math")
            ),
            "passes_traceability_gate": not any(
                item == "fewer_than_three_key_claims"
                or item == "fewer_than_three_source_anchors"
                or item.startswith("key_claim_missing_source_anchor:")
                for item in failures
            ),
            "passes_publication_hygiene_gate": not any(
                item in failures
                for item in (
                    "absolute_local_path_present",
                    "runtime_status_persisted",
                    "temporary_path_present",
                    "duplicate_english_title",
                    "published_html_comment_present",
                    "figure_placeholder_callout_present",
                    "figure_planning_label_present",
                    "source_figure_target_id_present",
                    "figure_qa_metadata_present",
                    "figure_process_metadata_present",
                )
            ),
        }
    )
    return artifact


LANGUAGE_FAILURES = {
    "mixed_language_lines_present",
    "suspicious_mid_sentence_linebreaks",
}


def visible_prose(text: str) -> str:
    """Return the reader-visible prose used by language heuristics."""
    body = parse_frontmatter(text).body
    body = re.sub(
        r"(?ms)^## 我的笔记\s*$.*?(?=^## |\Z)",
        "",
        body,
    )
    body = re.sub(
        r"（(?:主文|补充材料|SI|Supplement(?:ary)?)[^）\n]*）",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body = re.sub(r"\\\[.*?\\\]", "", body, flags=re.DOTALL)
    body = re.sub(r"\\\((?:\\.|[^\\\n])*?\\\)", "", body)
    body = re.sub(r"\$\$.*?\$\$", "", body, flags=re.DOTALL)
    body = re.sub(r"(?<!\\)\$(?:\\.|[^$\n])*?(?<!\\)\$", "", body)
    body = re.sub(r"!\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", "", body)
    body = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", body)
    body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    return body


_ORDERED_LIST_ITEM = re.compile(r"^\s*\d+[.)]\s+")


def visible_linebreak_issues(text: str) -> list[dict[str, object]]:
    """Return true prose wraps while excluding adjacent ordered-list items."""
    issues = suspicious_mid_sentence_linebreaks(text)
    return [
        issue
        for issue in issues
        if not (
            _ORDERED_LIST_ITEM.match(str(issue.get("line", "")))
            and _ORDERED_LIST_ITEM.match(str(issue.get("next_line", "")))
        )
    ]


def build_final_lint(text: str, context: dict[str, Any], *, input_path: str = "") -> dict[str, Any]:
    artifact = build_release_lint(text, context, input_path=input_path)
    prose = visible_prose(text)
    mixed = mixed_language_issues(prose)
    linebreaks = visible_linebreak_issues(prose)
    failures = [item for item in artifact.get("failures", []) if item not in LANGUAGE_FAILURES]
    if mixed:
        failures.append("mixed_language_lines_present")
    if linebreaks:
        failures.append("suspicious_mid_sentence_linebreaks")
    failures = list(dict.fromkeys(failures))
    artifact["failures"] = failures
    artifact["status"] = "pass" if not failures else "fail"
    artifact["mixed_language_issues"] = mixed
    artifact["linebreak_issues"] = linebreaks
    artifact["language_scope"] = (
        "visible_prose_without_frontmatter_evidence_anchors_links_code_or_math"
    )
    artifact["passes_style_gate"] = not any(
        item in LANGUAGE_FAILURES for item in failures
    ) and not any(item == "code_formatted_math_present" for item in failures)
    return artifact


def main() -> None:
    args = parser().parse_args()
    path = Path(args.input).expanduser().resolve()
    artifact = build_final_lint(
        path.read_text(encoding="utf-8"),
        load_json_object(args.context),
        input_path=str(path),
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

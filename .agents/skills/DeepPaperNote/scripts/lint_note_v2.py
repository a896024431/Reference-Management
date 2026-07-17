#!/usr/bin/env python3
"""Lint a DeepPaperNote v2 two-layer Markdown note and bind the report to its hash."""

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
from lint_note import (
    math_render_issues,
    mixed_language_issues,
    suspicious_code_formatted_math,
    suspicious_mid_sentence_linebreaks,
)

REQUIRED_PROPERTIES = (
    "type",
    "title",
    "title_zh",
    "authors",
    "year",
    "venue",
    "domain",
    "topics",
    "paper_type",
    "evidence_level",
    "note_status",
    "figure_status",
    "aliases",
    "tags",
)
ENUMS = {
    "evidence_level": {"abstract_only", "full_text", "full_text_supplement"},
    "note_status": {"draft", "reviewed", "polished", "degraded"},
    "figure_status": {"complete", "partial", "placeholder_only", "none_needed"},
}
QUICK_SECTIONS = ("30 秒速览", "关键结论", "适用边界", "快速入口")
DEEP_SECTIONS = (
    "原文摘要翻译",
    "研究问题",
    "主要结果与证据",
    "局限与未决问题",
    "相关论文",
    "引用",
)
DOMAIN_METHOD_SECTIONS = (
    "实验体系与测量",
    "理论模型",
    "材料与工艺",
    "方法主线",
    "研究材料与论证方法",
)
AI_LEAKAGE = (
    "不是机器学习任务",
    "不是数值预测任务",
    "输入是",
    "操作是",
    "输出是",
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True, help="Markdown note path.")
    command.add_argument(
        "--context", required=True, help="v2 synthesis_bundle or paper_record JSON."
    )
    command.add_argument("--output", default="")
    return command


def frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def scalar_property(yaml_text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.*?)\s*$", yaml_text)
    if not match:
        return ""
    value = match.group(1).strip().strip("\"'")
    return value


def list_property_has_value(yaml_text: str, key: str) -> bool:
    inline = scalar_property(yaml_text, key)
    if inline and inline not in {"[]", "null", "~"}:
        return True
    block = re.search(
        rf"(?ms)^{re.escape(key)}:\s*$\n((?:^[ \t]+-\s*.+$\n?)*)",
        yaml_text,
    )
    return bool(block and re.search(r"(?m)^\s+-\s*\S", block.group(1)))


def property_present(yaml_text: str, key: str) -> bool:
    if key in {"authors", "topics", "aliases", "tags"}:
        return list_property_has_value(yaml_text, key)
    return bool(re.search(rf"(?m)^{re.escape(key)}:\s*\S", yaml_text))


def context_paper_type(context: dict[str, Any]) -> str:
    if context.get("artifact_type") == "synthesis_bundle":
        return str(context.get("paper_type", "generic"))
    record = context.get("paper_record", {})
    metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
    return str(metadata.get("paper_type", "generic"))


def lint_note_text(text: str, context: dict[str, Any]) -> dict[str, Any]:
    require_v2_artifact(context, artifact_type={"synthesis_bundle", "paper_record"})
    yaml_text, body = frontmatter(text)
    failures: list[str] = []
    warnings: list[str] = []
    if not yaml_text:
        failures.append("frontmatter_missing")
    missing_properties = [
        key for key in REQUIRED_PROPERTIES if not property_present(yaml_text, key)
    ]
    if missing_properties:
        failures.append(f"frontmatter_missing_properties:{','.join(missing_properties)}")
    for key, allowed in ENUMS.items():
        value = scalar_property(yaml_text, key)
        if value and value not in allowed:
            failures.append(f"frontmatter_invalid_enum:{key}:{value}")
    paper_type_value = scalar_property(yaml_text, "paper_type")
    expected_type = context_paper_type(context)
    if paper_type_value and expected_type and paper_type_value != expected_type:
        failures.append(f"paper_type_mismatch:{paper_type_value}:{expected_type}")
    aliases_block = re.search(r"(?ms)^aliases:\s*$\n((?:^\s+-\s*.+$\n?)*)", yaml_text)
    if aliases_block and not re.search(r"[\u4e00-\u9fff]", aliases_block.group(1)):
        failures.append("aliases_missing_chinese_title")

    if not body.lstrip().startswith("# "):
        failures.append("title_heading_missing")
    headings = re.findall(r"(?m)^##\s+(.+?)\s*$", body)
    for section in (*QUICK_SECTIONS, *DEEP_SECTIONS):
        if section not in headings:
            failures.append(f"required_section_missing:{section}")
    if not any(section in headings for section in DOMAIN_METHOD_SECTIONS):
        failures.append("domain_method_section_missing")
    claim_section = re.search(
        r"(?ms)^##\s+关键结论\s*$\n(.*?)(?=^##\s+|\Z)",
        body,
    )
    claim_count = (
        len(re.findall(r"(?m)^\s*[-*]\s+\S", claim_section.group(1))) if claim_section else 0
    )
    if claim_count < 3:
        failures.append("fewer_than_three_key_claims")
    anchors = re.findall(r"(?:主文|补充材料)\s+p\.\s*\d+", body)
    if len(anchors) < 3:
        failures.append("fewer_than_three_source_anchors")
    if re.search(r"(?i)[A-Z]:\\Users\\|/Users/[^/]+/|/home/[^/]+/", text):
        failures.append("absolute_local_path_present")
    if "Zotero not available" in text:
        failures.append("runtime_status_persisted")
    if expected_type != "ai_method":
        leaked = [phrase for phrase in AI_LEAKAGE if phrase in body]
        if leaked:
            failures.append(f"ai_template_leakage:{','.join(leaked)}")

    mixed = mixed_language_issues(text)
    linebreaks = suspicious_mid_sentence_linebreaks(body)
    code_math = suspicious_code_formatted_math(text)
    math_issues = math_render_issues(text)
    if mixed:
        failures.append("mixed_language_lines_present")
    if linebreaks:
        failures.append("suspicious_mid_sentence_linebreaks")
    if code_math:
        failures.append("code_formatted_math_present")
    if math_issues:
        failures.append("math_render_issues_present")
    if "## 关键数字" not in body and re.search(r"\d+(?:\.\d+)?\s*(?:%|K|T|V|nm|μm|meV|Hz)\b", body):
        warnings.append("quantitative_paper_without_key_numbers_section")

    return {
        "failures": list(dict.fromkeys(failures)),
        "warnings": warnings,
        "missing_properties": missing_properties,
        "headings": headings,
        "source_anchor_count": len(anchors),
        "key_claim_count": claim_count,
        "mixed_language_issues": mixed,
        "linebreak_issues": linebreaks,
        "code_math_issues": code_math,
        "math_render_issues": math_issues,
    }


def build_lint_artifact(
    text: str, context: dict[str, Any], *, input_path: str = ""
) -> dict[str, Any]:
    details = lint_note_text(text, context)
    failures = details.pop("failures")
    artifact = artifact_header(
        "lint_report",
        paper_id=str(context["paper_id"]),
        run_id=str(context["run_id"]),
        status="pass" if not failures else "fail",
        failures=failures,
    )
    artifact.update(details)
    artifact["input_path"] = input_path
    artifact["note_sha256"] = sha256_text(text)
    artifact["passes_basic_structure"] = not any(
        item.startswith(("frontmatter_", "required_section_", "title_", "domain_method_"))
        for item in failures
    )
    artifact["passes_style_gate"] = not any(
        item in failures
        for item in (
            "mixed_language_lines_present",
            "suspicious_mid_sentence_linebreaks",
            "code_formatted_math_present",
        )
    )
    artifact["passes_math_gate"] = "math_render_issues_present" not in failures
    artifact["passes_traceability_gate"] = not any(
        item in failures
        for item in ("fewer_than_three_key_claims", "fewer_than_three_source_anchors")
    )
    artifact["passes_publication_hygiene_gate"] = not any(
        item in failures for item in ("absolute_local_path_present", "runtime_status_persisted")
    )
    return artifact


def main() -> None:
    args = parser().parse_args()
    note_path = Path(args.input).expanduser().resolve()
    note_text = note_path.read_text(encoding="utf-8")
    artifact = build_lint_artifact(
        note_text,
        load_json_object(args.context),
        input_path=str(note_path),
    )
    emit_json(artifact, args.output or None)
    if artifact["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

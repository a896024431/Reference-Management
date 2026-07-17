#!/usr/bin/env python3
"""Final release lint that evaluates visible prose instead of markup internals.

The v2 release linter intentionally reuses the structural, traceability, math,
and publication-hygiene gates.  For language and line-break checks it removes
frontmatter, link destinations, HTML comments, code fences, and TeX math first.
Those tokens are machine syntax rather than prose shown to the reader, and
counting them produced false positives for valid Chinese notes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from contracts_v2 import emit_json, load_json_object
from lint_note import mixed_language_issues, suspicious_mid_sentence_linebreaks
from lint_note_release_v2 import build_release_lint
from vault import parse_frontmatter

LANGUAGE_FAILURES = {
    "mixed_language_lines_present",
    "suspicious_mid_sentence_linebreaks",
}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", required=True)
    command.add_argument("--context", required=True, help="v2 synthesis bundle or paper record")
    command.add_argument("--output", default="")
    return command


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

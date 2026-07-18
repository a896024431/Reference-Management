#!/usr/bin/env python3
"""Provide shared language, math, and Markdown lint helpers for lint_note_v2."""

from __future__ import annotations

import re

ENGLISH_FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "both",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "we",
    "when",
    "which",
    "with",
}

DOUBLE_ESCAPED_TEX_COMMANDS = {
    "alpha",
    "bar",
    "begin",
    "beta",
    "end",
    "exp",
    "frac",
    "gamma",
    "ge",
    "hat",
    "left",
    "le",
    "log",
    "mathcal",
    "mathrm",
    "prod",
    "right",
    "sum",
    "tau",
    "tilde",
}


def is_metadata_line(line: str) -> bool:
    stripped = line.strip()
    prefixes = [
        "- 标题:",
        "- 标题翻译:",
        "- 作者:",
        "- 机构:",
        "- 发表时间:",
        "- 会议 / 期刊:",
        "- DOI:",
        "- 论文链接:",
        "- 论文类型:",
        "- 链接:",
    ]
    return any(stripped.startswith(prefix) for prefix in prefixes)


def is_exempt_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    if is_metadata_line(stripped):
        return True
    if (
        stripped.startswith("> 建议位置：")
        or stripped.startswith("> 放置原因：")
        or stripped.startswith("> 当前状态：")
    ):
        return True
    if re.search(r"https?://", stripped):
        return True
    if re.search(r"`10\.\d{4,9}/", stripped):
        return True
    return False


def section_name_for_line(lines: list[str], line_index: int) -> str:
    current_section = ""
    for idx in range(0, line_index + 1):
        stripped = lines[idx].strip()
        match = re.match(r"^##\s+(.+)$", stripped)
        if match:
            current_section = match.group(1).strip()
    return current_section


def mixed_language_issues(text: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if is_exempt_line(line):
            continue
        stripped = line.strip()
        section_name = section_name_for_line(lines, idx - 1)
        if section_name in {"核心信息", "引用"}:
            continue
        if not re.search(r"[\u4e00-\u9fff]", stripped):
            continue
        english_words = re.findall(r"\b[A-Za-z][A-Za-z0-9.-]*\b", stripped)
        if len(english_words) < 4:
            continue
        function_hits = [word for word in english_words if word.lower() in ENGLISH_FUNCTION_WORDS]
        if not function_hits and len(english_words) < 7:
            continue
        issues.append(
            {
                "line_number": idx,
                "line": stripped,
                "english_word_count": len(english_words),
                "function_word_hits": function_hits[:6],
            }
        )
    return issues


def is_prose_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "-", "*", "> ", "```", "![[", "*论文原图编号")):
        return False
    if stripped.startswith("`") and stripped.endswith("`"):
        return False
    return True


def suspicious_mid_sentence_linebreaks(text: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    lines = text.splitlines()
    for idx in range(len(lines) - 1):
        current = lines[idx].rstrip()
        nxt = lines[idx + 1].lstrip()
        if not is_prose_line(current) or not is_prose_line(nxt):
            continue
        if is_metadata_line(current) or is_metadata_line(nxt):
            continue
        if re.search(r"[。！？.!?：:]$", current):
            continue
        if not re.search(r"[，,；;、）)\]」』]$", current):
            if not re.search(r"[A-Za-z0-9`\u4e00-\u9fff]$", current):
                continue
        if not re.match(r"^[A-Za-z0-9`\u4e00-\u9fff(（“‘\"]", nxt):
            continue
        issues.append(
            {
                "line_number": idx + 1,
                "line": current.strip(),
                "next_line": nxt.strip(),
            }
        )
    return issues


def suspicious_code_formatted_math(text: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    lines = text.splitlines()
    in_fence = False
    fence_start = 0
    fence_lines: list[str] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = idx
                fence_lines = []
            else:
                fence_text = "\n".join(fence_lines)
                if re.search(
                    r"(?:^|\\n)\s*(?:[A-Za-z][A-Za-z0-9_]*\s*=|O\(|\\sum|\\prod|\\mathcal|\\log|\\frac)",
                    fence_text,
                ):
                    issues.append(
                        {
                            "line_number": fence_start,
                            "line": "```",
                            "next_line": fence_lines[0].strip() if fence_lines else "",
                            "kind": "fenced_math_like_block",
                        }
                    )
                in_fence = False
                fence_start = 0
                fence_lines = []
            continue
        if in_fence:
            fence_lines.append(line)
            continue
        for match in re.finditer(r"`([^`\n]{3,120})`", line):
            content = match.group(1).strip()
            if re.search(r"(=|O\(|\\sum|\\prod|\\mathcal|\\log|\\frac)", content):
                issues.append(
                    {
                        "line_number": idx,
                        "line": line.strip(),
                        "next_line": content,
                        "kind": "inline_code_math_like",
                    }
                )
                break
    return issues


def _line_number_from_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _formula_snippet(content: str, limit: int = 120) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _strip_fenced_code_preserve_newlines(text: str) -> str:
    return re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)


def _extract_math_blocks(text: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sanitized = _strip_fenced_code_preserve_newlines(text)
    blocks: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    consumed_lines: set[int] = set()

    block_pattern = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", flags=re.DOTALL)
    for match in block_pattern.finditer(sanitized):
        start = match.start()
        line_number = _line_number_from_offset(sanitized, start)
        content = match.group(1).strip()
        blocks.append(
            {
                "kind": "block",
                "line_number": line_number,
                "content": content,
                "snippet": _formula_snippet(content),
            }
        )
        line_span = match.group(0).count("\n")
        for extra in range(line_span + 1):
            consumed_lines.add(line_number + extra)

    delimiter_positions = [m.start() for m in re.finditer(r"(?<!\\)\$\$", sanitized)]
    if len(delimiter_positions) % 2 == 1:
        offset = delimiter_positions[-1]
        issues.append(
            {
                "line_number": _line_number_from_offset(sanitized, offset),
                "snippet": "$$",
                "reason": "unclosed_math_delimiter",
            }
        )

    inline_pattern = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)")
    for idx, line in enumerate(sanitized.splitlines(), start=1):
        if idx in consumed_lines:
            continue
        for match in inline_pattern.finditer(line):
            content = match.group(1).strip()
            if not content:
                continue
            blocks.append(
                {
                    "kind": "inline",
                    "line_number": idx,
                    "content": content,
                    "snippet": _formula_snippet(content),
                }
            )
        if len(re.findall(r"(?<!\\)(?<!\$)\$(?!\$)", line)) % 2 == 1:
            issues.append(
                {
                    "line_number": idx,
                    "snippet": line.strip(),
                    "reason": "unclosed_math_delimiter",
                }
            )
    return blocks, issues


def _find_unbalanced_braces(expr: str) -> bool:
    depth = 0
    for char in expr:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


def _parse_group_argument(expr: str, start: int) -> int | None:
    idx = start
    while idx < len(expr) and expr[idx].isspace():
        idx += 1
    if idx >= len(expr) or expr[idx] != "{":
        return None
    depth = 0
    while idx < len(expr):
        if expr[idx] == "{":
            depth += 1
        elif expr[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx + 1
        idx += 1
    return None


def _has_invalid_frac_arguments(expr: str) -> bool:
    for match in re.finditer(r"(?<!\\)\\frac\b", expr):
        next_index = _parse_group_argument(expr, match.end())
        if next_index is None:
            return True
        final_index = _parse_group_argument(expr, next_index)
        if final_index is None:
            return True
    return False


def _has_environment_mismatch(expr: str) -> bool:
    stack: list[str] = []
    pattern = re.compile(r"(?<!\\)\\(begin|end)\{([A-Za-z*]+)\}")
    for kind, env in pattern.findall(expr):
        if kind == "begin":
            stack.append(env)
            continue
        if not stack or stack[-1] != env:
            return True
        stack.pop()
    return bool(stack)


def _has_left_right_mismatch(expr: str) -> bool:
    return len(re.findall(r"(?<!\\)\\left\b", expr)) != len(re.findall(r"(?<!\\)\\right\b", expr))


def _has_double_escaped_tex_command(expr: str) -> bool:
    pattern = r"(?<!\\)\\\\(" + "|".join(sorted(DOUBLE_ESCAPED_TEX_COMMANDS)) + r")\b"
    return bool(re.search(pattern, expr))


def math_render_issues(text: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    blocks, delimiter_issues = _extract_math_blocks(text)
    issues.extend(delimiter_issues)

    for block in blocks:
        content = str(block["content"])
        line_number = int(block["line_number"])
        snippet = str(block["snippet"])

        if _has_double_escaped_tex_command(content):
            issues.append(
                {
                    "line_number": line_number,
                    "snippet": snippet,
                    "reason": "double_escaped_tex_command",
                }
            )
        if _find_unbalanced_braces(content):
            issues.append(
                {
                    "line_number": line_number,
                    "snippet": snippet,
                    "reason": "unbalanced_braces",
                }
            )
        if _has_environment_mismatch(content):
            issues.append(
                {
                    "line_number": line_number,
                    "snippet": snippet,
                    "reason": "environment_mismatch",
                }
            )
        if _has_left_right_mismatch(content):
            issues.append(
                {
                    "line_number": line_number,
                    "snippet": snippet,
                    "reason": "left_right_mismatch",
                }
            )
        if _has_invalid_frac_arguments(content):
            issues.append(
                {
                    "line_number": line_number,
                    "snippet": snippet,
                    "reason": "invalid_frac_arguments",
                }
            )

    deduped: list[dict[str, object]] = []
    seen: set[tuple[int, str, str]] = set()
    for issue in issues:
        key = (int(issue["line_number"]), str(issue["snippet"]), str(issue["reason"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped

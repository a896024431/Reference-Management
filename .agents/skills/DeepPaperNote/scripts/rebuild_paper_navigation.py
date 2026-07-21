#!/usr/bin/env python3
"""Regenerate a compact 文献/论文导航.md from validated paper notes."""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from vault import (
    NAVIGATION_PATH,
    NoteRecord,
    discover_notes,
    note_wikilink,
    validate_frontmatter_properties,
)


def _navigation_sort_key(record: NoteRecord) -> tuple[int, str, str]:
    year = str(record.properties.get("year", "")).strip()
    numeric_year = int(year) if year.isdigit() else 0
    return (
        -numeric_year,
        str(record.properties.get("title_zh") or record.folder_name).casefold(),
        str(record.properties.get("title") or record.folder_name).casefold(),
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "rebuild paper navigation")
    p.add_argument("--vault", default=".", help="Obsidian vault root.")
    p.add_argument(
        "--check", action="store_true", help="Exit non-zero when the existing file is stale."
    )
    p.add_argument(
        "--stdout", action="store_true", help="Print generated Markdown without writing."
    )
    return p


def render_navigation(vault_root: Path) -> str:
    records = discover_notes(vault_root)
    invalid: list[str] = []
    for record in records:
        if record.parse_errors or validate_frontmatter_properties(record.properties):
            invalid.append(record.relative_path)
    if invalid:
        joined = "\n- ".join(invalid)
        raise ValueError(
            f"Cannot regenerate navigation until every note has valid v2 properties:\n- {joined}"
        )

    records = sorted(records, key=_navigation_sort_key)

    lines = [
        "---",
        "type: navigation",
        "aliases:",
        "  - 论文导航",
        "tags:",
        "  - vault/navigation",
        "---",
        "",
        "# 论文导航",
        "",
        (
            "这里是当前 Vault 的论文入口。属性、主题和待补图状态可在核心 Base 中筛选；"
            "下方为每篇论文保留一个直接链接。"
        ),
        "",
        "![[论文库.base]]",
        "",
        "## 论文列表",
        "",
    ]
    if records:
        for record in records:
            year = str(record.properties.get("year", "")).strip()
            suffix = f"（{year}）" if year else ""
            lines.append(f"- {note_wikilink(record)}{suffix}")
    else:
        lines.append("- 暂无论文")
    lines.append("")
    lines.extend(
        [
            "## 使用方式",
            "",
            "- 想按属性筛选时，打开或展开 `论文库.base`。",
            "- 想浏览研究脉络时，从论文列表进入，并结合每篇笔记的“相关论文”继续跳转。",
            "- `note_status`、`evidence_level` 和 `figure_status` 是完成度判断依据。",
            "",
        ]
    )
    return "\n".join(lines)


def write_navigation_atomic(vault_root: Path, content: str | None = None) -> Path:
    """Replace the navigation note atomically using deterministic UTF-8/LF bytes."""
    target = vault_root / NAVIGATION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    generated = render_navigation(vault_root) if content is None else content
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(generated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def main() -> None:
    args = parser().parse_args()
    vault_root = Path(args.vault).expanduser().resolve()
    generated = render_navigation(vault_root)
    target = vault_root / NAVIGATION_PATH
    if args.stdout:
        print(generated, end="")
        return
    if args.check:
        existing = target.read_text(encoding="utf-8-sig") if target.exists() else ""
        if existing != generated:
            raise SystemExit("文献/论文导航.md is stale; rerun rebuild_paper_navigation.py")
        return
    write_navigation_atomic(vault_root, generated)


if __name__ == "__main__":
    main()

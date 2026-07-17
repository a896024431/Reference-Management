#!/usr/bin/env python3
"""Regenerate Research/论文导航.md from validated v2 paper topics."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from vault import (
    NAVIGATION_PATH,
    NoteRecord,
    discover_notes,
    note_wikilink,
    validate_frontmatter_properties,
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


def controlled_topics(record: NoteRecord) -> list[str]:
    """Return a stable, case-insensitively de-duplicated topic list."""
    raw_topics = record.properties.get("topics", [])
    if not isinstance(raw_topics, list):
        return []
    topics: list[str] = []
    seen: set[str] = set()
    for raw_topic in raw_topics:
        topic = str(raw_topic).strip()
        key = topic.casefold()
        if topic and key not in seen:
            topics.append(topic)
            seen.add(key)
    return topics


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

    grouped: dict[str, list[NoteRecord]] = defaultdict(list)
    topic_labels: dict[str, str] = {}
    for record in records:
        topics = controlled_topics(record)
        if not topics:
            raise ValueError(f"Validated note has no controlled topics: {record.relative_path}")
        for topic in topics:
            topic_key = topic.casefold()
            topic_labels.setdefault(topic_key, topic)
            grouped[topic_key].append(record)

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
            "这里是当前 Vault 的论文入口。属性筛选、待补图和待复核状态见核心 Base；"
            "下方按受控主题生成真实 wikilink，确保每篇论文都可到达。"
        ),
        "",
        "![[论文库.base]]",
        "",
        "## 主题索引",
        "",
        "同一篇论文可以出现在多个主题下；每个条目都是可解析的真实 wikilink。",
        "",
    ]
    for topic_key in sorted(grouped):
        topic = topic_labels[topic_key]
        lines.extend([f"### {topic}", ""])
        records_in_topic = sorted(
            grouped[topic_key],
            key=lambda record: (
                str(record.properties.get("title_zh") or record.folder_name).casefold(),
                str(record.properties.get("title") or record.folder_name).casefold(),
            ),
        )
        for record in records_in_topic:
            lines.append(f"- {note_wikilink(record)}")
        lines.append("")
    lines.extend(
        [
            "## 使用方式",
            "",
            "- 想按属性筛选时，打开或展开 `论文库.base`。",
            "- 想浏览研究脉络时，从上面的主题入口进入论文，并结合每篇笔记的“相关论文”继续跳转。",
            "- `note_status`、`evidence_level` 和 `figure_status` 是完成度判断依据。",
            "",
        ]
    )
    return "\n".join(lines)


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
            raise SystemExit("Research/论文导航.md is stale; rerun rebuild_paper_navigation.py")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generated, encoding="utf-8")


if __name__ == "__main__":
    main()

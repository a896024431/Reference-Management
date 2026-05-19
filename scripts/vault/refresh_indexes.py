from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


INDEX_FILES = {
    "文献索引.md",
    "研究主题索引.md",
    "研究方法索引.md",
    "字段补全检查.md",
}

REQUIRED_FIELDS = [
    "title",
    "author",
    "year",
    "theme",
    "study_area",
    "data_source",
    "methodology",
    "core_variable",
    "key_finding",
    "relevance",
    "zotero_key",
    "collection",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh static Markdown indexes for the research vault.")
    parser.add_argument("--vault-root", default=".")
    parser.add_argument("--notes-dir", default="note")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if indexes are stale")
    return parser.parse_args()


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].splitlines()
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in raw:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, [])
            if isinstance(metadata[current_key], list):
                metadata[current_key].append(strip_quotes(line[4:]))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            metadata[key] = strip_quotes(value) if value else ""
            current_key = key
    return metadata, text[end + 4 :]


def first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def discover_notes(vault_root: Path, notes_dir: str) -> list[dict[str, Any]]:
    root = vault_root / notes_dir
    if not root.exists():
        return []
    notes = []
    for path in sorted(root.rglob("*.md")):
        if path.name in INDEX_FILES or path.name == "_ProcessLog_进度记录.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        title = str(metadata.get("title") or first_heading(body) or path.stem)
        rel = path.relative_to(vault_root).as_posix()
        notes.append({"path": path, "rel": rel, "title": title, "metadata": metadata})
    return notes


def md_escape(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    value = "" if value is None else str(value)
    return value.replace("|", "\\|").replace("\n", " ").strip()


def md_link(note: dict[str, Any]) -> str:
    return f"[打开](<{note['rel']}>)"


def render_literature_index(notes: list[dict[str, Any]]) -> str:
    lines = [
        "# 文献索引",
        "",
        "> 由 `scripts/vault/refresh_indexes.py` 生成。手工编辑会在下次刷新时被覆盖。",
        "",
        "| 标题 | 年份 | 作者 | 主题 | 方法 | Collection | 路径 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for note in notes:
        meta = note["metadata"]
        lines.append(
            "| {title} | {year} | {author} | {theme} | {method} | {collection} | {path} |".format(
                title=md_escape(note["title"]),
                year=md_escape(meta.get("year", "")),
                author=md_escape(meta.get("author", "")),
                theme=md_escape(meta.get("theme", "")),
                method=md_escape(meta.get("methodology", "")),
                collection=md_escape(meta.get("collection", "")),
                path=md_link(note),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_group_index(notes: list[dict[str, Any]], field: str, title: str) -> str:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        key = md_escape(note["metadata"].get(field, "")) or "未填写"
        groups[key].append(note)
    lines = [
        f"# {title}",
        "",
        "> 由 `scripts/vault/refresh_indexes.py` 生成。手工编辑会在下次刷新时被覆盖。",
        "",
    ]
    if not groups:
        lines.append("暂无文献。")
        return "\n".join(lines).rstrip() + "\n"
    for key in sorted(groups):
        lines.extend([f"## {key}", ""])
        for note in groups[key]:
            meta = note["metadata"]
            year = md_escape(meta.get("year", ""))
            author = md_escape(meta.get("author", ""))
            lines.append(f"- {md_escape(note['title'])}（{year}，{author}） - {md_link(note)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def missing_fields(note: dict[str, Any]) -> list[str]:
    meta = note["metadata"]
    missing = []
    for field in REQUIRED_FIELDS:
        value = meta.get(field, "")
        if value in ("", "用一句话概括论文主题", "用一句话概括最关键研究发现"):
            missing.append(field)
    return missing


def render_field_check(notes: list[dict[str, Any]]) -> str:
    rows = []
    for note in notes:
        missing = missing_fields(note)
        if missing:
            rows.append((note, missing))
    lines = [
        "# 字段补全检查",
        "",
        "> 由 `scripts/vault/refresh_indexes.py` 生成。手工编辑会在下次刷新时被覆盖。",
        "",
    ]
    if not rows:
        lines.append("暂无缺失字段记录。")
        return "\n".join(lines).rstrip() + "\n"
    lines.extend(["| 标题 | 缺失字段 | 路径 |", "| --- | --- | --- |"])
    for note, missing in rows:
        lines.append(
            f"| {md_escape(note['title'])} | {md_escape(', '.join(missing))} | {md_link(note)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_indexes(vault_root: Path, notes_dir: str) -> dict[Path, str]:
    notes = discover_notes(vault_root, notes_dir)
    return {
        vault_root / "文献索引.md": render_literature_index(notes),
        vault_root / "研究主题索引.md": render_group_index(notes, "theme", "研究主题索引"),
        vault_root / "研究方法索引.md": render_group_index(notes, "methodology", "研究方法索引"),
        vault_root / "字段补全检查.md": render_field_check(notes),
    }


def main() -> int:
    args = parse_args()
    vault_root = Path(args.vault_root).resolve()
    indexes = build_indexes(vault_root, args.notes_dir)
    stale = []
    for path, content in indexes.items():
        if args.check:
            current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            if current != content:
                stale.append(path)
            continue
        path.write_text(content, encoding="utf-8")
    if stale:
        for path in stale:
            print(f"Stale index: {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

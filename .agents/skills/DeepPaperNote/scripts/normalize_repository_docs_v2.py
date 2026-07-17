#!/usr/bin/env python3
"""Remove obsolete Zotero/sync statements from root docs after enabling v2."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

AGENTS_OLD = (
    "1. 目前暂不配置 Zotero 联动，也不安装 Zotero MCP。\n"
    "2. 若当前 Codex 会话没有 Zotero 工具，记录为 `Zotero not available`，"
    "然后继续使用 PDF、DOI、arXiv、URL 或开放元数据来源。"
)

AGENTS_NEW = (
    "1. Zotero/infiniCloud 是可选联动来源；运行时先探测已有通道，"
    "但本仓库不自动安装 Zotero MCP。\n"
    "2. 通道可用时优先使用可信本地库元数据与附件；"
    "不可用时继续使用本地 PDF、DOI、arXiv 或 URL。"
    "可用性只记录在 run manifest，禁止写入永久笔记。"
)

README_ZOTERO = """## Zotero（可选来源）

Zotero/infiniCloud 已按可选 provider 设计。DeepPaperNote 在运行时探测现有通道：可信本地库
命中优先于标题联网匹配；当前会话没有可调用通道时，继续使用本地 PDF、DOI、arXiv 或
开放元数据。集成状态只进入运行清单，不写入永久笔记，也不会自动安装 Zotero MCP。

不要提交 Zotero 数据库、PDF、附件、全文缓存或本机路径配置。

"""


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--vault-root", default=".")
    return command


def _atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.normalize-v2.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    args = parser().parse_args()
    root = Path(args.vault_root).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = root / ".local" / "deeppapernote" / "repository-config-backups" / timestamp
    backup_root.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []

    agents = root / "AGENTS.md"
    before = agents.read_text(encoding="utf-8-sig")
    after = before.replace(AGENTS_OLD, AGENTS_NEW)
    sync_anchor = "- `.agents/skills/DeepPaperNote/`\n"
    sync_addition = (
        sync_anchor + "- `.github/workflows/deeppapernote-v2.yml`\n- `Research/*.base`\n"
    )
    if "- `.github/workflows/deeppapernote-v2.yml`" not in after:
        after = after.replace(sync_anchor, sync_addition)
    if after != before:
        shutil.copy2(agents, backup_root / agents.name)
        _atomic(agents, after)
        changed.append("AGENTS.md")

    readme = root / "README.md"
    before = readme.read_text(encoding="utf-8-sig")
    after, count = re.subn(
        r"(?ms)^## Zotero 状态\s*\n.*?(?=^## DeepPaperNote\s*$)",
        README_ZOTERO,
        before,
        count=1,
    )
    if count != 1 and "## Zotero（可选来源）" not in before:
        raise SystemExit("Could not find the legacy Zotero section in README.md")
    if after != before:
        shutil.copy2(readme, backup_root / readme.name)
        _atomic(readme, after)
        changed.append("README.md")

    print(
        json.dumps(
            {"schema_version": "2.0", "status": "pass", "changed": changed}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()

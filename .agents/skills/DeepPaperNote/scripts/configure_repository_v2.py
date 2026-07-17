#!/usr/bin/env python3
"""Apply the root-level repository routing and sync policy for DeepPaperNote v2."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

GITIGNORE_BLOCK = """

# DeepPaperNote v2 local-only outputs.
.local/
tmp/
DeepPaperNote_output/

# DeepPaperNote v2 tracked Vault/CI assets.
!.github/
!.github/workflows/
!.github/workflows/deeppapernote-v2.yml
!Research/*.base
"""

AGENTS_V2_BLOCK = """

## DeepPaperNote v2 overlay

当前 Vault 使用 schema v2 overlay。读取 `SKILL.md` 及其必需 references 后，还必须读取：

- `.agents/skills/DeepPaperNote/references/v2-workflow.md`
- `.agents/skills/DeepPaperNote/references/vault-v2.md`

确定性入口使用 `scripts/run_pipeline_final_v2.py`，中间产物默认写入
`.local/deeppapernote/runs/<run_id>/`。正式笔记发布必须通过 v2 合同、证据、插图、
可读性与 Vault 门禁；旧 MVP 脚本只作为兼容回退，不得静默发布 schema v2 笔记。

Zotero/infiniCloud 是可选 provider：运行时先探测并优先使用可信本地库命中；不可用时回退
本地 PDF、DOI 或 arXiv。可用性只进入 run manifest，不得把 `Zotero not available`
写进永久笔记。本轮不自动安装 Zotero MCP。
"""

README_V2_BLOCK = """

## DeepPaperNote v2

当前 Vault 使用单文件双层笔记：每篇仍保存为 `Research/<论文标题>/笔记.md`，顶部提供
“30 秒速览、关键结论、关键数字、适用边界、快速入口”，下方保留带页码证据锚点的完整精读。

确定性管线入口是：

```powershell
C:\\Users\\chen\\AppData\\Local\\Programs\\Python\\Python311\\python.exe `
  .agents\\skills\\DeepPaperNote\\scripts\\run_pipeline_final_v2.py --help
```

Obsidian 入口包括 `Research/论文导航.md` 和核心 Bases 文件 `Research/论文库.base`；无需
Dataview。运行产物与迁移备份位于 `.local/deeppapernote/`，并从 Obsidian 搜索中排除。

Zotero/infiniCloud 作为可选元数据和跳转来源。管线会在运行时探测；不可用时自动使用本地
PDF 和稳定标识符，且不会把集成状态写进永久笔记。
"""


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--vault-root", default=".")
    command.add_argument("--dry-run", action="store_true")
    return command


def _append_once(text: str, marker: str, block: str) -> tuple[str, bool]:
    if marker in text:
        return text, False
    return text.rstrip() + block + "\n", True


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.deeppapernote-v2.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def configure(vault_root: Path, *, dry_run: bool = False) -> dict[str, object]:
    vault_root = vault_root.expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = vault_root / ".local" / "deeppapernote" / "repository-config-backups" / timestamp
    specs = (
        (vault_root / ".gitignore", "# DeepPaperNote v2 tracked Vault/CI assets.", GITIGNORE_BLOCK),
        (vault_root / "AGENTS.md", "## DeepPaperNote v2 overlay", AGENTS_V2_BLOCK),
        (vault_root / "README.md", "## DeepPaperNote v2", README_V2_BLOCK),
    )
    changed: list[str] = []
    backups: list[str] = []
    for path, marker, block in specs:
        before = path.read_text(encoding="utf-8-sig")
        after, did_change = _append_once(before, marker, block)
        if not did_change:
            continue
        changed.append(str(path.relative_to(vault_root)))
        if dry_run:
            continue
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / path.name
        shutil.copy2(path, backup)
        backups.append(str(backup))
        _atomic_write(path, after)

    return {
        "schema_version": "2.0",
        "status": "dry_run" if dry_run else "pass",
        "changed": changed,
        "backups": backups,
    }


def main() -> None:
    args = parser().parse_args()
    result = configure(Path(args.vault_root), dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

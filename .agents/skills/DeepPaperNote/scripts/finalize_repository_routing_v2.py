#!/usr/bin/env python3
"""Finalize repository documentation and CI routing for the v2 release chain.

This migration is idempotent and creates timestamped local backups before the
three tracked configuration files are atomically replaced.  It exists because
the Windows sandbox cannot patch already-existing files in this workspace.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKUP_ROOT = ROOT / ".local" / "deeppapernote" / "repository-config-backups"

ROUTING_BLOCK = """

### v2 最终发布链

正式入口与门禁依次为：

- `scripts/run_pipeline_final_v2.py`
- `scripts/lint_note_final_v2.py`
- `scripts/build_figure_contact_sheet_v2.py`
- `scripts/record_figure_visual_review_v2.py`
- `scripts/publish_note_final_v2.py`

插图决策改变后必须重建 contact sheet 与视觉复核；任何 `reject` 资源都不能通过人工复核改写为
`inserted`。正式发布只消费与笔记、manifest 和 decisions 哈希一致的通过产物。
"""


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp-v2-routing")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _update_markdown(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text.replace("scripts/run_pipeline_v2.py", "scripts/run_pipeline_final_v2.py")
    updated = updated.replace("scripts\\run_pipeline_v2.py", "scripts\\run_pipeline_final_v2.py")
    if "### v2 最终发布链" not in updated:
        updated = updated.rstrip() + ROUTING_BLOCK + "\n"
    if updated == text:
        return False
    _atomic_write(path, updated)
    return True


def _update_workflow(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text.replace("Check canonical v2 entrypoint", "Check final v2 entrypoint")
    updated = updated.replace("run_pipeline_canonical_v2.py", "run_pipeline_final_v2.py")
    if updated == text:
        return False
    _atomic_write(path, updated)
    return True


def main() -> None:
    targets = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        ROOT / ".github" / "workflows" / "deeppapernote-v2.yml",
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_ROOT / stamp
    changed: list[str] = []
    for target in targets:
        if not target.is_file():
            raise SystemExit(f"Required repository file is missing: {target}")
        relative = target.relative_to(ROOT)
        backup_path = backup / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
        was_changed = (
            _update_workflow(target) if target.suffix == ".yml" else _update_markdown(target)
        )
        if was_changed:
            changed.append(relative.as_posix())
    print(f"backup={backup}")
    print("changed=" + ",".join(changed))


if __name__ == "__main__":
    main()

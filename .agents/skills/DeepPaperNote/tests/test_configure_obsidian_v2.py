from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from configure_obsidian_v2 import (  # noqa: E402
    DEFAULT_IGNORE_FILTERS,
    clean_recent_files,
    configure_obsidian,
    merge_ignore_filters,
)


class ObsidianConfigTests(unittest.TestCase):
    def test_merge_is_idempotent_and_preserves_settings(self) -> None:
        original = {"attachmentFolderPath": "assets", "userIgnoreFilters": [r"^Archive/"]}
        first, added = merge_ignore_filters(original)
        second, added_again = merge_ignore_filters(first)
        self.assertEqual(first["attachmentFolderPath"], "assets")
        self.assertEqual(added, list(DEFAULT_IGNORE_FILTERS))
        self.assertEqual(first, second)
        self.assertEqual(added_again, [])

    def test_clean_recent_removes_only_generated_paths(self) -> None:
        workspace = {
            "active": "leaf-id",
            "lastOpenFiles": [
                "tmp/run/draft.md",
                ".local/deeppapernote/run.json",
                "DeepPaperNote_output/old.md",
                "Research/Paper/笔记.md",
                "Research/tmp analysis/笔记.md",
            ],
        }
        cleaned, removed = clean_recent_files(workspace)
        self.assertEqual(len(removed), 3)
        self.assertEqual(
            cleaned["lastOpenFiles"],
            ["Research/Paper/笔记.md", "Research/tmp analysis/笔记.md"],
        )
        self.assertEqual(cleaned["active"], "leaf-id")

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            app_path = vault / ".obsidian" / "app.json"
            app_path.parent.mkdir(parents=True)
            app_path.write_text('{"showUnsupportedFiles": true}\n', encoding="utf-8")
            before = app_path.read_text(encoding="utf-8")
            result = configure_obsidian(vault, dry_run=True)
            self.assertTrue(result["app_changed"])
            self.assertEqual(app_path.read_text(encoding="utf-8"), before)

    def test_configure_writes_backup_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            obsidian = vault / ".obsidian"
            obsidian.mkdir(parents=True)
            (obsidian / "app.json").write_text('{"showUnsupportedFiles": true}\n', encoding="utf-8")
            (obsidian / "workspace.json").write_text(
                json.dumps({"lastOpenFiles": ["tmp/draft.md", "Research/Paper/笔记.md"]}),
                encoding="utf-8",
            )

            first = configure_obsidian(vault, clean_recent=True)
            second = configure_obsidian(vault, clean_recent=True)
            app = json.loads((obsidian / "app.json").read_text(encoding="utf-8"))
            workspace = json.loads((obsidian / "workspace.json").read_text(encoding="utf-8"))

            self.assertEqual(app["userIgnoreFilters"], list(DEFAULT_IGNORE_FILTERS))
            self.assertEqual(workspace["lastOpenFiles"], ["Research/Paper/笔记.md"])
            self.assertEqual(len(first["backups"]), 2)
            self.assertFalse(second["app_changed"])
            self.assertFalse(second["workspace_changed"])
            self.assertEqual(second["backups"], [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import rebuild_paper_navigation  # noqa: E402
from rebuild_paper_navigation import render_navigation, write_navigation_atomic  # noqa: E402
from vault import NOTE_FILENAME, render_frontmatter  # noqa: E402


def properties(title: str, title_zh: str, domain: str, topics: list[str]) -> dict[str, object]:
    return {
        "type": "paper",
        "title": title,
        "title_zh": title_zh,
        "authors": ["A. Author"],
        "year": "2025",
        "venue": "Test Journal",
        "domain": domain,
        "topics": topics,
        "paper_type": "generic",
        "evidence_level": "full_text",
        "note_status": "reviewed",
        "figure_status": "none_needed",
        "aliases": [title, title_zh],
        "tags": ["papers/general"],
    }


class NavigationGenerationTests(unittest.TestCase):
    def test_lists_each_paper_once_and_keeps_base_embed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            papers = (
                (
                    "Paper A",
                    "\u8bba\u6587\u7532",
                    "\u91cf\u5b50\u8f93\u8fd0",
                    ["quantum-transport", "shared-topic", "QUANTUM-TRANSPORT"],
                ),
                (
                    "Paper B",
                    "\u8bba\u6587\u4e59",
                    "\u7eb3\u7c73\u52a0\u5de5",
                    ["nanofabrication", "SHARED-TOPIC"],
                ),
            )
            for title, title_zh, domain, topics in papers:
                paper_dir = vault / "Research" / title
                (paper_dir / "images").mkdir(parents=True)
                (paper_dir / NOTE_FILENAME).write_text(
                    render_frontmatter(properties(title, title_zh, domain, topics))
                    + f"\n# {title_zh}\n",
                    encoding="utf-8",
                )

            generated = render_navigation(vault)

            self.assertIn("![[\u8bba\u6587\u5e93.base]]", generated)
            self.assertIn("## \u8bba\u6587\u5217\u8868", generated)
            self.assertNotIn("### quantum-transport", generated)
            paper_a_link = f"[[Research/Paper A/{NOTE_FILENAME[:-3]}|\u8bba\u6587\u7532]]"
            paper_b_link = f"[[Research/Paper B/{NOTE_FILENAME[:-3]}|\u8bba\u6587\u4e59]]"
            self.assertEqual(generated.count(paper_a_link), 1)
            self.assertEqual(generated.count(paper_b_link), 1)
            self.assertEqual(generated.count(f"/{NOTE_FILENAME[:-3]}|"), 2)

    def test_refuses_legacy_note_without_v2_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            paper_dir = vault / "Research" / "Legacy"
            paper_dir.mkdir(parents=True)
            (paper_dir / NOTE_FILENAME).write_text("# Legacy\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                render_navigation(vault)

    def test_atomic_write_preserves_previous_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            target = vault / "Research" / "论文导航.md"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old\r\ncontent\r\n")

            with patch.object(
                rebuild_paper_navigation.os,
                "replace",
                side_effect=OSError("simulated replacement failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    write_navigation_atomic(vault, "new\ncontent\n")

            self.assertEqual(target.read_bytes(), b"old\r\ncontent\r\n")
            self.assertEqual(list(target.parent.glob(".论文导航.md.tmp-*")), [])

    def test_atomic_write_uses_lf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)

            target = write_navigation_atomic(vault, "line one\nline two\n")

            self.assertEqual(target.read_bytes(), b"line one\nline two\n")


if __name__ == "__main__":
    unittest.main()

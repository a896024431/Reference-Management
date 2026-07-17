from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from rebuild_paper_navigation import render_navigation  # noqa: E402
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
    def test_groups_by_controlled_topics_with_multi_membership_and_deduplication(self) -> None:
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

            self.assertIn("## \u4e3b\u9898\u7d22\u5f15", generated)
            self.assertEqual(generated.count("### quantum-transport"), 1)
            self.assertEqual(generated.count("### shared-topic"), 1)
            self.assertEqual(generated.count("### nanofabrication"), 1)
            paper_a_link = f"[[Research/Paper A/{NOTE_FILENAME[:-3]}|\u8bba\u6587\u7532]]"
            paper_b_link = f"[[Research/Paper B/{NOTE_FILENAME[:-3]}|\u8bba\u6587\u4e59]]"
            self.assertEqual(generated.count(paper_a_link), 2)
            self.assertEqual(generated.count(paper_b_link), 2)
            self.assertEqual(generated.count(f"/{NOTE_FILENAME[:-3]}|"), 4)
            self.assertLess(
                generated.index("### nanofabrication"),
                generated.index("### quantum-transport"),
            )

    def test_refuses_legacy_note_without_v2_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            paper_dir = vault / "Research" / "Legacy"
            paper_dir.mkdir(parents=True)
            (paper_dir / NOTE_FILENAME).write_text("# Legacy\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                render_navigation(vault)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from vault import (  # noqa: E402
    BASE_PATH,
    build_note_index,
    discover_notes,
    lint_vault,
    paper_local_image_names,
    parse_base_definition,
    parse_frontmatter,
    render_frontmatter,
    resolve_link_target,
    validate_frontmatter_properties,
    validate_image_file,
)

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_reader_images_must_be_reviewed_paper_local_embeds() -> None:
    names, failures = paper_local_image_names(
        "![remote](https://example.org/figure.png)\n"
        "![protocol-relative](//example.org/figure.png)\n"
        "![reference][fig]\n[fig]: https://example.org/figure.png\n"
        "![shortcut]\n[shortcut]: https://example.org/figure.png\n"
        '<img src="images/figure.png">\n'
        "![[images/local.png]]\n"
    )

    assert names == {"local.png"}
    assert "external_image_forbidden:https://example.org/figure.png" in failures
    assert "external_image_forbidden://example.org/figure.png" in failures
    assert "reference_image_embed_forbidden" in failures
    assert "html_image_embed_forbidden" in failures


def valid_properties(title: str = "Paper One") -> dict[str, object]:
    return {
        "type": "paper",
        "title": title,
        "title_zh": "论文一",
        "authors": ["Alice Example", "Bob Example"],
        "year": "2024",
        "venue": "Physical Review Letters",
        "domain": "condensed-matter physics",
        "topics": ["quantum-hall", "edge-transport"],
        "paper_type": "experimental_physics",
        "evidence_level": "full_text_supplement",
        "note_status": "polished",
        "figure_status": "complete",
        "aliases": ["Paper One", "论文一"],
        "tags": ["papers/physics/condensed-matter"],
        "doi": "10.1234/example",
    }


def base_text() -> str:
    return """filters:
  and:
    - 'file.inFolder("Research")'
    - 'file.name == "笔记"'
views:
  - type: table
    name: 全部论文
  - type: table
    name: 待补图
  - type: table
    name: 待复核
  - type: table
    name: 按主题
"""


def build_vault(root: Path, *, with_image: bool = False) -> Path:
    paper_dir = root / "Research" / "Paper One"
    image_dir = paper_dir / "images"
    image_dir.mkdir(parents=True)
    image_block = ""
    if with_image:
        (image_dir / "fig-1.png").write_bytes(ONE_PIXEL_PNG)
        image_block = "\n![[images/fig-1.png]]\n"
    note = render_frontmatter(valid_properties()) + "\n# 论文一\n" + image_block
    (paper_dir / "笔记.md").write_text(note, encoding="utf-8")
    (root / "Research" / "论文库.base").write_text(base_text(), encoding="utf-8")
    (root / "Research" / "论文导航.md").write_text(
        "# 论文导航\n\n![[论文库.base]]\n\n- [[Research/Paper One/笔记|论文一]]\n",
        encoding="utf-8",
    )
    return paper_dir / "笔记.md"


class FrontmatterTests(unittest.TestCase):
    def test_render_parse_round_trip(self) -> None:
        properties = valid_properties()
        rendered = render_frontmatter(properties)
        parsed = parse_frontmatter(rendered + "\n# 论文一\n")
        self.assertEqual(parsed.errors, ())
        self.assertEqual(parsed.properties, properties)
        self.assertIn("# 论文一", parsed.body)

    def test_missing_frontmatter_is_explicit(self) -> None:
        parsed = parse_frontmatter("# Title\n")
        self.assertEqual(parsed.errors, ("frontmatter_missing",))
        self.assertEqual(parsed.properties, {})

    def test_contract_requires_chinese_and_latin_aliases(self) -> None:
        properties = valid_properties()
        properties["aliases"] = ["Paper One"]
        codes = {issue["code"] for issue in validate_frontmatter_properties(properties)}
        self.assertIn("chinese_alias_missing", codes)

    def test_contract_rejects_old_taxonomy_and_invalid_enum(self) -> None:
        properties = valid_properties()
        properties["tags"] = ["papers/Condensed_Matter_Physics"]
        properties["paper_type"] = "AI_method"
        codes = {issue["code"] for issue in validate_frontmatter_properties(properties)}
        self.assertIn("tag_taxonomy_invalid", codes)
        self.assertIn("property_enum_invalid", codes)

    def test_contract_rejects_absolute_local_source(self) -> None:
        properties = valid_properties()
        properties["local_pdf"] = r"C:\Users\reader\paper.pdf"
        codes = {issue["code"] for issue in validate_frontmatter_properties(properties)}
        self.assertIn("local_source_absolute", codes)

class LinkResolutionTests(unittest.TestCase):
    def test_resolves_alias_and_doi(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = build_vault(root)
            records = discover_notes(root)
            index = build_note_index(records)
            alias = resolve_link_target(
                "论文一", source_path=source, vault_root=root, note_index=index
            )
            doi = resolve_link_target(
                "10.1234/example", source_path=source, vault_root=root, note_index=index
            )
            self.assertEqual(alias.status, "resolved")
            self.assertEqual(doi.status, "resolved")
            self.assertEqual(alias.path, source)

    def test_missing_link_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = build_vault(root)
            index = build_note_index(discover_notes(root))
            result = resolve_link_target(
                "Paper Missing", source_path=source, vault_root=root, note_index=index
            )
            self.assertEqual(result.status, "missing")


class BaseDefinitionTests(unittest.TestCase):
    def test_parses_exact_filters_and_four_official_views(self) -> None:
        definition = parse_base_definition(base_text())
        self.assertEqual(
            definition.global_filters,
            ('file.inFolder("Research")', 'file.name == "\u7b14\u8bb0"'),
        )
        self.assertEqual(
            definition.views,
            (
                "\u5168\u90e8\u8bba\u6587",
                "\u5f85\u8865\u56fe",
                "\u5f85\u590d\u6838",
                "\u6309\u4e3b\u9898",
            ),
        )

    def test_comments_cannot_fake_required_filters_or_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_vault(root)
            fake_base = """filters:
  and:
    - 'type == "paper"'
# - 'file.inFolder("Research")'
# - 'file.name == "\u7b14\u8bb0"'
views:
  - type: table
    name: \u5176\u5b83
# name: \u5168\u90e8\u8bba\u6587
# name: \u5f85\u8865\u56fe
# name: \u5f85\u590d\u6838
# name: \u6309\u4e3b\u9898
"""
            (root / BASE_PATH).write_text(fake_base, encoding="utf-8")

            codes = {issue["code"] for issue in lint_vault(root)["issues"]}

            self.assertIn("paper_base_view_missing", codes)
            self.assertIn("paper_base_view_unexpected", codes)
            self.assertIn("paper_base_filter_invalid", codes)


class VaultLintTests(unittest.TestCase):
    def test_clean_synthetic_vault_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_vault(root, with_image=True)
            report = lint_vault(root)
            self.assertEqual(
                report["status"], "pass", json.dumps(report["issues"], ensure_ascii=False)
            )
            self.assertEqual(report["summary"]["navigation_coverage"], 1)

    def test_note_without_empty_images_directory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            (note_path.parent / "images").rmdir()

            report = lint_vault(root)

            self.assertEqual(
                report["status"], "pass", json.dumps(report["issues"], ensure_ascii=False)
            )

    def test_broken_link_and_missing_navigation_entry_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            note_path.write_text(
                note_path.read_text(encoding="utf-8") + "\n[[Missing Paper]]\n", encoding="utf-8"
            )
            (root / "Research" / "论文导航.md").write_text(
                "# 论文导航\n\n![[论文库.base]]\n", encoding="utf-8"
            )
            codes = {issue["code"] for issue in lint_vault(root)["issues"]}
            self.assertIn("wikilink_broken", codes)
            self.assertIn("note_missing_from_navigation", codes)

    def test_ci_mode_allows_only_missing_local_pdf_library_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            local_pdf_target = "\u6587\u732e/1/local-only.pdf"
            note_path.write_text(
                note_path.read_text(encoding="utf-8")
                + f"\n[[{local_pdf_target}|Local PDF]]\n[[Missing Paper]]\n",
                encoding="utf-8",
            )

            strict_targets = {
                issue["details"].get("target")
                for issue in lint_vault(root)["issues"]
                if issue["code"] == "wikilink_broken"
            }
            ci_targets = {
                issue["details"].get("target")
                for issue in lint_vault(root, allow_missing_local_pdfs=True)["issues"]
                if issue["code"] == "wikilink_broken"
            }

            self.assertEqual(strict_targets, {local_pdf_target, "Missing Paper"})
            self.assertEqual(ci_targets, {"Missing Paper"})

    def test_runtime_status_and_absolute_path_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            note_path.write_text(
                note_path.read_text(encoding="utf-8")
                + "\nZotero not available. Source: C:\\Users\\reader\\paper.pdf\n",
                encoding="utf-8",
            )
            codes = {issue["code"] for issue in lint_vault(root)["issues"]}
            self.assertIn("runtime_status_present", codes)
            self.assertIn("absolute_path_present", codes)

    def test_orphan_and_corrupt_images_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_vault(root)
            image_path = root / "Research" / "Paper One" / "images" / "orphan.png"
            image_path.write_bytes(b"not a png")
            report = lint_vault(root)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("image_orphan", codes)
            self.assertIn("image_corrupt", codes)

    def test_no_note_directory_and_its_images_cannot_hide_from_vault_lint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_vault(root)
            stray_images = root / "Research" / "No Note" / "images"
            stray_images.mkdir(parents=True)
            (stray_images / "orphan.png").write_bytes(b"not a png")

            report = lint_vault(root)
            codes = {issue["code"] for issue in report["issues"]}

            self.assertEqual(report["summary"]["images"], 1)
            self.assertIn("paper_directory_note_missing", codes)
            self.assertIn("image_orphan", codes)
            self.assertIn("image_corrupt", codes)

    def test_raster_must_decode_not_merely_resemble_a_png_container(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_vault(root)
            image_path = root / "Research" / "Paper One" / "images" / "fake.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nnot-pixels-IEND")

            self.assertTrue(validate_image_file(image_path).startswith("raster_decode_failed:"))

    def test_paper_directory_and_images_reject_extra_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            paper_dir = note_path.parent
            (paper_dir / "manifest.json").write_text("{}", encoding="utf-8")
            (paper_dir / "scratch").mkdir()
            (paper_dir / "images" / "notes.txt").write_text("no", encoding="utf-8")
            (paper_dir / "images" / "nested").mkdir()

            codes = {issue["code"] for issue in lint_vault(root)["issues"]}

            self.assertIn("paper_directory_extra_entry", codes)
            self.assertIn("image_extension_unsupported", codes)
            self.assertIn("images_extra_entry", codes)

    def test_reader_visible_figure_workflow_metadata_fails_vault_lint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            note_path.write_text(
                note_path.read_text(encoding="utf-8")
                + "\n> [!figure] Fig. 2\n> 当前状态：候选裁剪已通过 QA。\n"
                + "doc:main|fig-2\n",
                encoding="utf-8",
            )

            codes = {issue["code"] for issue in lint_vault(root)["issues"]}

            self.assertIn("figure_placeholder_callout_present", codes)
            self.assertIn("figure_planning_label_present", codes)
            self.assertIn("source_figure_target_id_present", codes)

    def test_remote_and_html_images_fail_vault_lint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_path = build_vault(root)
            note_path.write_text(
                note_path.read_text(encoding="utf-8")
                + "\n![remote](https://example.org/unreviewed.png)\n"
                + '<img src="images/unreviewed.png">\n',
                encoding="utf-8",
            )

            codes = {issue["code"] for issue in lint_vault(root)["issues"]}

            self.assertIn("external_image_forbidden", codes)
            self.assertIn("html_image_embed_forbidden", codes)

    def test_referenced_valid_image_is_not_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_vault(root, with_image=True)
            image_path = root / "Research" / "Paper One" / "images" / "fig-1.png"
            self.assertEqual(validate_image_file(image_path), "")
            image_issues = [
                issue
                for issue in lint_vault(root)["issues"]
                if issue["code"] in {"image_orphan", "image_corrupt"}
            ]
            self.assertEqual(image_issues, [])


if __name__ == "__main__":
    unittest.main()

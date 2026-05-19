from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "zotero"))
sys.path.insert(0, str(ROOT / "scripts" / "vault"))

import process_collection
import refresh_indexes
import zotero_db


class WorkflowTests(unittest.TestCase):
    def create_zotero_fixture(self, root: Path) -> Path:
        data_dir = root / "zotero"
        data_dir.mkdir()
        db = data_dir / "zotero.sqlite"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE itemTypes(itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            CREATE TABLE items(itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, key TEXT, dateAdded TEXT, dateModified TEXT);
            CREATE TABLE fields(fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            CREATE TABLE itemData(itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            CREATE TABLE itemDataValues(valueID INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE creators(creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INTEGER);
            CREATE TABLE creatorTypes(creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE itemCreators(itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE collections(collectionID INTEGER PRIMARY KEY, collectionName TEXT, key TEXT);
            CREATE TABLE collectionItems(collectionID INTEGER, itemID INTEGER, orderIndex INTEGER);
            CREATE TABLE itemAttachments(itemID INTEGER, parentItemID INTEGER, path TEXT, contentType TEXT);
            CREATE TABLE itemAnnotations(itemID INTEGER, parentItemID INTEGER, type TEXT, text TEXT, comment TEXT, color TEXT, pageLabel TEXT, sortIndex TEXT);
            CREATE TABLE itemNotes(itemID INTEGER, parentItemID INTEGER, note TEXT);
            """
        )
        conn.executemany("INSERT INTO itemTypes VALUES (?, ?)", [(1, "journalArticle"), (2, "attachment"), (3, "annotation"), (4, "note")])
        conn.executemany(
            "INSERT INTO items VALUES (?, ?, ?, ?, ?)",
            [
                (1, 1, "ABCD1234", "2024-01-01", "2024-01-02"),
                (2, 2, "ATTACH01", "2024-01-01", "2024-01-02"),
                (3, 3, "ANNOT001", "2024-01-01", "2024-01-02"),
                (4, 4, "NOTE0001", "2024-01-01", "2024-01-02"),
            ],
        )
        fields = [(1, "title"), (2, "date"), (3, "publicationTitle"), (4, "DOI"), (5, "abstractNote")]
        values = [
            (1, "Urban Innovation Spaces"),
            (2, "2023"),
            (3, "Journal of Cities"),
            (4, "10.1234/example"),
            (5, "This paper studies innovation spaces."),
        ]
        conn.executemany("INSERT INTO fields VALUES (?, ?)", fields)
        conn.executemany("INSERT INTO itemDataValues VALUES (?, ?)", values)
        conn.executemany("INSERT INTO itemData VALUES (1, ?, ?)", [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])
        conn.execute("INSERT INTO creators VALUES (1, 'Jane', 'Doe', 0)")
        conn.execute("INSERT INTO creatorTypes VALUES (1, 'author')")
        conn.execute("INSERT INTO itemCreators VALUES (1, 1, 1, 0)")
        conn.execute("INSERT INTO collections VALUES (1, 'Test Collection', 'COLL0001')")
        conn.execute("INSERT INTO collectionItems VALUES (1, 1, 0)")
        conn.execute("INSERT INTO itemAttachments VALUES (2, 1, 'storage:paper.pdf', 'application/pdf')")
        conn.execute("INSERT INTO itemAnnotations VALUES (3, 2, 'highlight', 'Key annotation text', '', '#ffd400', '12', '0001')")
        conn.execute("INSERT INTO itemNotes VALUES (4, 1, '<p>Reader note</p>')")
        conn.commit()
        conn.close()

        storage = data_dir / "storage" / "ATTACH01"
        storage.mkdir(parents=True)
        (storage / "paper.pdf").write_bytes(b"%PDF-1.4")
        (storage / ".zotero-ft-cache").write_text("Full text cache content", encoding="utf-8")
        return data_dir

    def test_extract_item_json_from_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_dir = self.create_zotero_fixture(Path(temp))
            with zotero_db.connect_snapshot(data_dir) as conn:
                data = zotero_db.extract_item(conn, data_dir, item_key="ABCD1234")
            self.assertEqual(data["metadata"]["title"], "Urban Innovation Spaces")
            self.assertEqual(data["creators"][0]["display_name"], "Jane Doe")
            self.assertEqual(data["attachments"][0]["attachmentKey"], "ATTACH01")
            self.assertIn("Key annotation text", data["raw_data_buffer"])
            self.assertIn("Full text cache content", data["raw_data_buffer"])

    def test_collection_pending_skips_process_log_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_dir = self.create_zotero_fixture(root)
            log = process_collection.process_log_path(root, "note", "Test Collection")
            process_collection.ensure_process_log(log, "Test Collection")
            log.write_text("- [x] 2026-05-19 10:00 | ✅ 成功 | ABCD1234 | Urban Innovation Spaces\n", encoding="utf-8")
            with zotero_db.connect_snapshot(data_dir) as conn:
                items = process_collection.collection_items(conn, "Test Collection")
            pending = process_collection.pending_items(items, process_collection.read_completed_keys(log))
            self.assertEqual(pending, [])

    def test_refresh_indexes_detects_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            note_dir = root / "note" / "Test Collection"
            note_dir.mkdir(parents=True)
            (note_dir / "paper.md").write_text(
                """---
title: "Urban Innovation Spaces"
author: "Jane Doe"
year: "2023"
theme: "城市创新空间研究"
methodology: "GIS 空间分析"
collection: "Test Collection"
zotero_key: "ABCD1234"
---

# Urban Innovation Spaces
""",
                encoding="utf-8",
            )
            indexes = refresh_indexes.build_indexes(root, "note")
            self.assertIn("Urban Innovation Spaces", indexes[root / "文献索引.md"])
            self.assertIn("城市创新空间研究", indexes[root / "研究主题索引.md"])
            self.assertIn("data_source", indexes[root / "字段补全检查.md"])

    def test_skill_frontmatter_has_required_fields(self) -> None:
        for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), path)
            end = text.find("\n---", 4)
            self.assertGreater(end, 0, path)
            frontmatter = text[4:end]
            self.assertIn(f"name: {path.parent.name}", frontmatter)
            self.assertIn("description:", frontmatter)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_zotero_pdfs.py"
SPEC = importlib.util.spec_from_file_location("zotero_pdf_sync", SCRIPT)
assert SPEC and SPEC.loader
sync_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_module)


def file_record(
    key: str, path: Path, *, deleted: bool = False, filename: str | None = None
) -> dict[str, object]:
    data: dict[str, object] = {
        "itemType": "attachment",
        "contentType": "application/pdf",
        "deleted": deleted,
    }
    if filename is not None:
        data["filename"] = filename
    return {
        "key": key,
        "data": data,
        "links": {"enclosure": {"href": path.as_uri()}},
    }


def paper_record(
    key: str, title: str, attachments: list[dict[str, object]], *, collection: tuple[str, ...] = ("QPC",)
) -> dict[str, object]:
    return {"key": key, "title": title, "collection": collection, "attachments": attachments}


class FakeApi:
    def __init__(self, main: Path, supplement: Path) -> None:
        self.main = main
        self.supplement = supplement
        self.collection_name = "QPC"
        self.include_nested = False
        self.include_root_item = False
        self.include_root_standalone = False
        self.standalone_title = "Root Standalone"
        self.duplicate_membership = False

    def request_json(self, _base: str, path: str) -> list[dict[str, object]]:
        if path.startswith("users/0/collections?"):
            collections = [
                {"key": "zju", "data": {"name": "ZJU", "parentCollection": False}},
                {"key": "group", "data": {"name": "课题组", "parentCollection": "zju"}},
                {"key": "qpc", "data": {"name": self.collection_name, "parentCollection": "group"}},
            ]
            if self.include_nested:
                collections.append(
                    {"key": "nested", "data": {"name": "Inner", "parentCollection": "qpc"}}
                )
            if self.duplicate_membership:
                collections.append(
                    {"key": "alt", "data": {"name": "Alt", "parentCollection": "group"}}
                )
            return collections
        if "/collections/zju/items/top" in path:
            return []
        if "/collections/group/items/top" in path:
            items: list[dict[str, object]] = []
            if self.include_root_item:
                items.append(
                    {
                        "key": "ROOT0001",
                        "data": {"itemType": "journalArticle", "title": "Root Paper"},
                    }
                )
            if self.include_root_standalone:
                standalone = file_record("ROOTPDF1", self.main)
                standalone["data"] = {
                    "itemType": "attachment",
                    "contentType": "application/pdf",
                    "title": self.standalone_title,
                }
                items.append(standalone)
            return items
        if "/collections/qpc/items/top" in path:
            return [{"key": "PAPER001", "data": {"itemType": "journalArticle", "title": "Paper A"}}]
        if "/collections/nested/items/top" in path:
            return [{"key": "PAPER002", "data": {"itemType": "journalArticle", "title": "Paper B"}}]
        if "/collections/alt/items/top" in path:
            return [{"key": "PAPER001", "data": {"itemType": "journalArticle", "title": "Paper A"}}]
        if "/items/PAPER001/children" in path:
            return [
                file_record("MAIN0001", self.main),
                file_record("SUPP0001", self.supplement),
                {"key": "HTML0001", "data": {"itemType": "attachment", "contentType": "text/html"}},
                file_record("DELETED1", self.main, deleted=True),
            ]
        if "/items/PAPER002/children" in path:
            return [file_record("NESTED01", self.main)]
        if "/items/ROOT0001/children" in path:
            return [file_record("ROOTMAIN", self.main)]
        raise AssertionError(path)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeApi:
    main = tmp_path / "source-main.pdf"
    supplement = tmp_path / "source-si.pdf"
    main.write_bytes(b"main-v1")
    supplement.write_bytes(b"supplement-v1")
    api = FakeApi(main, supplement)
    monkeypatch.setattr(sync_module, "_json_request", api.request_json)
    return api


def papers(fake_api: FakeApi) -> list[dict[str, object]]:
    return sync_module._collect_papers("http://fake/api", "ZJU/课题组", "", "")


def test_collects_nested_pdf_attachments_only(fake_api: FakeApi) -> None:
    result = papers(fake_api)

    assert len(result) == 1
    assert result[0]["collection"] == ("QPC",)
    assert [item["key"] for item in result[0]["attachments"]] == ["MAIN0001", "SUPP0001"]


def test_collects_descendant_collections_recursively(fake_api: FakeApi) -> None:
    fake_api.include_nested = True

    result = papers(fake_api)

    assert [(paper["key"], paper["collection"]) for paper in result] == [
        ("PAPER001", ("QPC",)),
        ("PAPER002", ("QPC", "Inner")),
    ]


def test_rejects_items_in_multiple_root_collections_before_writing(fake_api: FakeApi, tmp_path: Path) -> None:
    fake_api.duplicate_membership = True
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(sync_module.SyncError, match="多个 Zotero 分类"):
        papers(fake_api)

    assert not (vault / "文献").exists()


def test_maps_root_collection_items_to_uncategorized_directory(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    fake_api.include_root_item = True
    collected = papers(fake_api)
    root_item = next(paper for paper in collected if paper["key"] == "ROOT0001")

    assert root_item["collection"] == (sync_module.UNCATEGORIZED_COLLECTION,)

    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, collected, "http://fake/api", "ZJU/课题组", False)
    target = vault / "文献" / "未分类" / "Root Paper"
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))

    assert (target / "source-main.pdf").is_file()
    assert not (vault / "文献" / "Root Paper").exists()
    assert index["items"]["ROOT0001"]["relative_dir"] == "文献/未分类/Root Paper"


def test_root_collection_item_migrates_legacy_shallow_directory_without_a_note(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    fake_api.include_root_item = True
    vault = tmp_path / "vault"
    legacy_dir = vault / "文献" / "Root Paper"
    legacy_dir.mkdir(parents=True)
    legacy_pdf = legacy_dir / "source-main.pdf"
    legacy_pdf.write_bytes(fake_api.main.read_bytes())
    index_path = vault / ".local" / "zotero-pdf-sync" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": {
                    "ROOT0001": {
                        "title": "Root Paper",
                        "collection_path": [],
                        "relative_dir": "文献/Root Paper",
                        "attachments": {
                            "ROOTMAIN": {
                                "relative_path": "文献/Root Paper/source-main.pdf",
                                "sha256": sync_module._sha256(legacy_pdf),
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(sync_module.SyncError, match="只能在一次完整同步中迁移"):
        sync_module.sync(
            vault,
            papers(fake_api),
            "http://fake/api",
            "ZJU/课题组",
            False,
        )
    assert legacy_dir.is_dir()
    assert json.loads(index_path.read_text(encoding="utf-8"))["version"] == 1

    result = sync_module.sync(
        vault,
        papers(fake_api),
        "http://fake/api",
        "ZJU/课题组",
        False,
        complete=True,
    )

    assert not legacy_dir.exists()
    assert (vault / "文献" / "未分类" / "Root Paper" / "source-main.pdf").is_file()
    assert len(result["moved_directories"]) == 1
    migrated = json.loads(index_path.read_text(encoding="utf-8"))
    assert migrated["version"] == sync_module.INDEX_VERSION
    assert migrated["items"]["ROOT0001"]["collection_parts"] == ["未分类"]
    assert migrated["items"]["ROOT0001"]["folder_name"] == "Root Paper"
    assert migrated["items"]["ROOT0001"]["attachments"]["ROOTMAIN"]["filename"] == (
        "source-main.pdf"
    )


def test_maps_root_standalone_pdf_to_an_uncategorized_directory(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    fake_api.include_root_standalone = True

    collected = papers(fake_api)
    standalone = next(paper for paper in collected if paper["key"] == "ROOTPDF1")

    assert standalone["collection"] == (sync_module.UNCATEGORIZED_COLLECTION,)
    assert standalone["title"] == "Root Standalone"
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, collected, "http://fake/api", "ZJU/课题组", False)

    assert (
        vault
        / "文献"
        / "未分类"
        / "Root Standalone"
        / "source-main.pdf"
    ).is_file()


def test_standalone_pdf_without_a_title_never_uses_its_key_as_a_directory(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    key_named_source = tmp_path / "ROOTPDF1.pdf"
    key_named_source.write_bytes(b"standalone")
    fake_api.main = key_named_source
    fake_api.include_root_standalone = True
    fake_api.standalone_title = ""

    with pytest.raises(sync_module.SyncError, match="不能用 Zotero key"):
        papers(fake_api)


def test_sanitizes_windows_device_names_without_losing_pdf_extension() -> None:
    assert sync_module._safe_name("CON.pdf", "fallback.pdf") == "CON_.pdf"


def test_invalid_zotero_collection_name_never_falls_back_to_its_key() -> None:
    collections = {
        "group": {"name": "课题组", "parent": "root"},
        "bad-key": {"name": '<>:"/\\|?*', "parent": "group"},
    }

    with pytest.raises(sync_module.SyncError, match="Zotero 分类 bad-key 的名称"):
        sync_module._relative_collection(collections, "group", "bad-key")


def test_first_sync_and_unchanged_refresh(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    first = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    paper_dir = vault / "文献" / "QPC" / "Paper A"

    assert sorted(path.name for path in paper_dir.glob("*.pdf")) == [
        "source-main.pdf",
        "source-si.pdf",
    ]
    assert len(first["copied"]) == 2
    assert (vault / ".local" / "zotero-pdf-sync" / "index.json").is_file()

    second = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    assert len(second["unchanged"]) == 2
    assert second["copied"] == []


def test_changed_pdf_replaces_mirrored_attachment_when_paper_has_note(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    destination = vault / "文献" / "QPC" / "Paper A" / "source-main.pdf"
    (destination.parent / "笔记.md").write_text("note", encoding="utf-8")
    fake_api.main.write_bytes(b"main-v2")

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)

    assert destination.read_bytes() == b"main-v2"
    assert len(result["copied"]) == 1
    assert (destination.parent / "笔记.md").read_text(encoding="utf-8") == "note"
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))
    assert index["items"]["PAPER001"]["attachments"]["MAIN0001"]["filename"] == (
        "source-main.pdf"
    )


def test_move_without_note_follows_collection_rename(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    old_dir = vault / "文献" / "QPC" / "Paper A"
    fake_api.collection_name = "QPC Updated"

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)

    assert not old_dir.exists()
    assert (
        vault / "文献" / "QPC Updated" / "Paper A" / "source-main.pdf"
    ).is_file()
    assert len(result["moved_directories"]) == 1


def test_changed_pdf_refreshes_without_a_note(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    fake_api.main.write_bytes(b"main-v2")

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    destination = vault / "文献" / "QPC" / "Paper A" / "source-main.pdf"

    assert destination.read_bytes() == b"main-v2"
    assert len(result["copied"]) == 1


def test_move_with_note_moves_the_entire_paper_directory(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    old_dir = vault / "文献" / "QPC" / "Paper A"
    (old_dir / "笔记.md").write_text("note", encoding="utf-8")
    image_dir = old_dir / "images"
    image_dir.mkdir()
    (image_dir / "figure.png").write_bytes(b"image")
    fake_api.collection_name = "QPC Updated"

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))
    new_dir = vault / "文献" / "QPC Updated" / "Paper A"

    assert not old_dir.exists()
    assert (new_dir / "笔记.md").read_text(encoding="utf-8") == "note"
    assert (new_dir / "images" / "figure.png").read_bytes() == b"image"
    assert len(result["moved_directories"]) == 1
    assert index["items"]["PAPER001"]["relative_dir"] == "文献/QPC Updated/Paper A"


def test_scoped_refresh_keeps_unrelated_index_entries(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    one = tmp_path / "one.pdf"
    two = tmp_path / "two.pdf"
    one.write_bytes(b"one")
    two.write_bytes(b"two")
    first_paper = paper_record("PAPER001", "Paper A", [file_record("ATTACH001", one)])
    second_paper = paper_record("PAPER002", "Paper B", [file_record("ATTACH002", two)])

    sync_module.sync(vault, [first_paper, second_paper], "http://fake/api", "ZJU/课题组", False)
    sync_module.sync(vault, [first_paper], "http://fake/api", "ZJU/课题组", False)
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))

    assert set(index["items"]) == {"PAPER001", "PAPER002"}
    assert (vault / "文献" / "QPC" / "Paper B" / "two.pdf").is_file()
    assert not (vault / "文献" / sync_module.ARCHIVE_COLLECTION).exists()
    assert len(list((vault / ".local" / "zotero-pdf-sync" / "reports").glob("*.json"))) == 2


def test_scoped_same_title_refresh_reports_a_directory_conflict(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    first_source = tmp_path / "first.pdf"
    second_source = tmp_path / "second.pdf"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    first = paper_record("PAPER001", "Same title", [file_record("ATTACH001", first_source)])
    second = paper_record("PAPER002", "Same title", [file_record("ATTACH002", second_source)])

    sync_module.sync(vault, [first], "http://fake/api", "ZJU/课题组", False)
    first_dir = vault / "文献" / "QPC" / "Same title"
    (first_dir / "笔记.md").write_text("first note", encoding="utf-8")
    result = sync_module.sync(vault, [second], "http://fake/api", "ZJU/课题组", False, complete=False)
    assert (first_dir / "笔记.md").read_text(encoding="utf-8") == "first note"
    assert (first_dir / "first.pdf").is_file()
    assert not (first_dir / "second.pdf").exists()
    assert result["status"] == "attention"
    assert result["directory_conflicts"]


def test_title_change_moves_notes_images_and_pdfs(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    original = papers(fake_api)[0]
    sync_module.sync(vault, [original], "http://fake/api", "ZJU/课题组", False)
    old_dir = vault / "文献" / "QPC" / "Paper A"
    (old_dir / "笔记.md").write_text("note", encoding="utf-8")
    (old_dir / "images").mkdir()
    (old_dir / "images" / "kept.png").write_bytes(b"image")
    renamed = {**original, "title": "Paper A Updated"}

    result = sync_module.sync(vault, [renamed], "http://fake/api", "ZJU/课题组", False)

    new_dir = vault / "文献" / "QPC" / "Paper A Updated"
    assert not old_dir.exists()
    assert (new_dir / "笔记.md").read_text(encoding="utf-8") == "note"
    assert (new_dir / "images" / "kept.png").read_bytes() == b"image"
    assert (new_dir / "source-main.pdf").is_file()
    assert len(result["moved_directories"]) == 1


def test_attachment_rename_replaces_the_old_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    initial = paper_record(
        "PAPER001", "Paper A", [file_record("ATTACH001", source, filename="old name.pdf")]
    )
    renamed = paper_record(
        "PAPER001", "Paper A", [file_record("ATTACH001", source, filename="new name.pdf")]
    )
    sync_module.sync(vault, [initial], "http://fake/api", "ZJU/课题组", False)

    result = sync_module.sync(vault, [renamed], "http://fake/api", "ZJU/课题组", False)
    paper_dir = vault / "文献" / "QPC" / "Paper A"

    assert not (paper_dir / "old name.pdf").exists()
    assert (paper_dir / "new name.pdf").read_bytes() == b"pdf"
    assert len(result["renamed_attachments"]) == 1


def test_case_only_attachment_rename_preserves_the_current_pdf(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"before")
    initial = paper_record(
        "PAPER001", "Paper A", [file_record("ATTACH001", source, filename="Article.pdf")]
    )
    renamed = paper_record(
        "PAPER001", "Paper A", [file_record("ATTACH001", source, filename="article.pdf")]
    )
    sync_module.sync(vault, [initial], "http://fake/api", "ZJU/课题组", False)
    source.write_bytes(b"after")

    result = sync_module.sync(vault, [renamed], "http://fake/api", "ZJU/课题组", False)

    pdfs = list((vault / "文献" / "QPC" / "Paper A").glob("*.pdf"))
    assert [path.name for path in pdfs] == ["article.pdf"]
    assert pdfs[0].read_bytes() == b"after"
    assert len(result["renamed_attachments"]) == 1


@pytest.mark.parametrize("relative_dir", ["文献/QPC", "文献/QPC/子类"])
def test_malformed_v2_index_cannot_move_or_archive_a_category_directory(
    tmp_path: Path, relative_dir: str
) -> None:
    vault = tmp_path / "vault"
    managed_dir = vault / Path(*relative_dir.split("/"))
    managed_dir.mkdir(parents=True)
    marker = managed_dir / "keep.txt"
    marker.write_text("do not move", encoding="utf-8")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    index_path = vault / ".local" / "zotero-pdf-sync" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "version": sync_module.INDEX_VERSION,
                "items": {
                    "PAPER001": {
                        "relative_dir": relative_dir,
                        "collection_parts": ["QPC"],
                        "folder_name": "Paper A",
                        "attachments": {"ATTACH001": {"filename": "source.pdf"}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(sync_module.SyncError, match="身份不一致"):
        sync_module.sync(
            vault,
            [paper_record("PAPER001", "Paper A", [file_record("ATTACH001", source)])],
            "http://fake/api",
            "ZJU/课题组",
            False,
            complete=True,
        )

    assert marker.read_text(encoding="utf-8") == "do not move"
    assert not (vault / "文献" / sync_module.ARCHIVE_COLLECTION).exists()


def test_v2_index_without_directory_identity_is_rejected_before_writes(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    index_path = vault / ".local" / "zotero-pdf-sync" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "version": sync_module.INDEX_VERSION,
                "items": {
                    "PAPER001": {
                        "relative_dir": "文献/QPC/Paper A",
                        "attachments": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(sync_module.SyncError, match="collection_parts"):
        sync_module.sync(
            vault,
            [],
            "http://fake/api",
            "ZJU/课题组",
            False,
            complete=True,
        )

    assert not (vault / "文献").exists()


@pytest.mark.parametrize("title", ["", '<>:"/\\|?*'])
def test_empty_or_invalid_visible_title_is_rejected_without_creating_a_key_directory(
    tmp_path: Path, title: str
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")

    with pytest.raises(sync_module.SyncError, match="题名.*为空"):
        sync_module.sync(
            vault,
            [paper_record("PAPER001", title, [file_record("ATTACH001", source)])],
            "http://fake/api",
            "ZJU/课题组",
            False,
        )

    assert not (vault / "文献").exists()


def test_key_only_attachment_filename_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "ATTACH001.pdf"
    source.write_bytes(b"pdf")

    with pytest.raises(sync_module.SyncError, match="不能用 Zotero key"):
        sync_module.sync(
            vault,
            [paper_record("PAPER001", "Paper A", [file_record("ATTACH001", source)])],
            "http://fake/api",
            "ZJU/课题组",
            False,
        )

    assert not (vault / "文献").exists()


def test_complete_sync_archives_disappeared_item_without_recovery(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    paper = paper_record("PAPER001", "Paper A", [file_record("ATTACH001", source)])
    sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)
    active_dir = vault / "文献" / "QPC" / "Paper A"
    (active_dir / "笔记.md").write_text("archived note", encoding="utf-8")
    (active_dir / "images").mkdir()
    (active_dir / "images" / "kept.png").write_bytes(b"image")

    archived = sync_module.sync(vault, [], "http://fake/api", "ZJU/课题组", False, complete=True)
    archive_dir = vault / "文献" / sync_module.ARCHIVE_COLLECTION / "QPC" / "Paper A"
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))

    assert not active_dir.exists()
    assert (archive_dir / "笔记.md").read_text(encoding="utf-8") == "archived note"
    assert (archive_dir / "images" / "kept.png").read_bytes() == b"image"
    assert len(archived["archived_directories"]) == 1
    assert index["items"] == {}

    sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False, complete=True)
    assert (active_dir / "source.pdf").is_file()
    assert not (active_dir / "笔记.md").exists()
    assert (archive_dir / "笔记.md").is_file()


def test_rejects_reserved_archive_collection(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    paper = paper_record(
        "PAPER001",
        "Paper A",
        [file_record("ATTACH001", source)],
        collection=(sync_module.ARCHIVE_COLLECTION,),
    )

    with pytest.raises(sync_module.SyncError, match="保留归档目录"):
        sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)


def test_removed_attachments_are_deleted_but_the_note_directory_remains(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    original = papers(fake_api)[0]
    sync_module.sync(vault, [original], "http://fake/api", "ZJU/课题组", False)
    removed = {**original, "attachments": []}

    paper_dir = vault / "文献" / "QPC" / "Paper A"
    (paper_dir / "笔记.md").write_text("note", encoding="utf-8")
    result = sync_module.sync(vault, [removed], "http://fake/api", "ZJU/课题组", False, complete=True)

    assert len(result["deleted_attachments"]) == 2
    assert not list(paper_dir.glob("*.pdf"))
    assert (paper_dir / "笔记.md").read_text(encoding="utf-8") == "note"


def test_same_attachment_filename_is_reported_and_skipped(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "article.pdf"
    second = second_dir / "article.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    paper = paper_record(
        "PAPER001",
        "Paper A",
        [file_record("ATTACH001", first), file_record("ATTACH002", second)],
    )

    result = sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)

    assert result["status"] == "attention"
    assert result["file_conflicts"]
    assert not (vault / "文献" / "QPC" / "Paper A").exists()


def test_same_title_paper_directories_are_reported_and_skipped(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    papers_to_sync = [
        paper_record("PAPER001", "Same title", [file_record("ATTACH001", first)]),
        paper_record("PAPER002", "Same title", [file_record("ATTACH002", second)]),
    ]

    result = sync_module.sync(vault, papers_to_sync, "http://fake/api", "ZJU/课题组", False)

    assert result["status"] == "attention"
    assert len(result["directory_conflicts"]) == 2
    assert not (vault / "文献" / "QPC" / "Same title").exists()


def test_preserves_the_zotero_attachment_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "storage-name.pdf"
    source.write_bytes(b"pdf")
    paper = paper_record(
        "PAPER001",
        "Paper A",
        [file_record("ATTACH001", source, filename="Zotero attachment name.pdf")],
    )

    sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)

    assert (
        vault / "文献" / "QPC" / "Paper A" / "Zotero attachment name.pdf"
    ).is_file()


def test_removes_a_local_pdf_that_is_not_in_zotero(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "article.pdf"
    source.write_bytes(b"from-zotero")
    paper = paper_record("PAPER001", "Paper A", [file_record("ATTACH001", source)])
    sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)
    paper_dir = vault / "文献" / "QPC" / "Paper A"
    existing = paper_dir / "manual.pdf"
    existing.write_bytes(b"keep")

    result = sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)

    assert not existing.exists()
    assert result["status"] == "pass"
    assert any(item.get("reason") == "not_in_zotero" for item in result["deleted_attachments"])


def test_item_without_pdfs_does_not_create_an_empty_paper_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    no_pdf = paper_record("PAPER001", "No PDF", [])

    result = sync_module.sync(vault, [no_pdf], "http://fake/api", "ZJU/课题组", False)

    assert result["copied"] == []
    assert not (vault / "文献").exists()


def test_dry_run_creates_no_index(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", True)

    assert result["copied"]
    assert not (vault / ".local").exists()
    assert not (vault / "文献").exists()


def test_local_api_403_is_actionable_and_does_not_write(monkeypatch: pytest.MonkeyPatch) -> None:
    error = sync_module.urllib.error.HTTPError("http://localhost", 403, "Forbidden", {}, None)
    monkeypatch.setattr(sync_module, "_open", lambda *args, **kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(sync_module.SyncError, match="允许本机应用访问"):
        sync_module._json_request("http://localhost:23119/api", "users/0/collections")
    with pytest.raises(sync_module.SyncError, match="允许本机应用访问"):
        sync_module._text_request("http://localhost:23119/api", "users/0/items/ATTACH001/file/view/url")


def test_main_uses_the_fixed_local_api_and_root_collection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    collected: dict[str, object] = {}
    synced: dict[str, object] = {}

    def fake_collect(
        api_base: str, root_collection: str, collection: str, item_key: str
    ) -> list[dict[str, object]]:
        collected.update(
            api_base=api_base,
            root_collection=root_collection,
            collection=collection,
            item_key=item_key,
        )
        return []

    def fake_sync(
        vault: Path,
        papers_to_sync: list[dict[str, object]],
        api_base: str,
        root_collection: str,
        dry_run: bool,
        *,
        complete: bool = False,
    ) -> dict[str, str]:
        synced.update(
            vault=vault,
            papers=papers_to_sync,
            api_base=api_base,
            root_collection=root_collection,
            dry_run=dry_run,
            complete=complete,
        )
        return {"status": "pass"}

    monkeypatch.setattr(sync_module, "_collect_papers", fake_collect)
    monkeypatch.setattr(sync_module, "sync", fake_sync)
    monkeypatch.setattr(
        sync_module.sys,
        "argv",
        [str(SCRIPT), "--vault-root", str(tmp_path), "--collection", "QPC", "--dry-run"],
    )

    sync_module.main()

    assert collected == {
        "api_base": sync_module.API_BASE,
        "root_collection": sync_module.ROOT_COLLECTION,
        "collection": "QPC",
        "item_key": "",
    }
    assert synced == {
        "vault": tmp_path,
        "papers": [],
        "api_base": sync_module.API_BASE,
        "root_collection": sync_module.ROOT_COLLECTION,
        "dry_run": True,
        "complete": False,
    }
    assert json.loads(capsys.readouterr().out) == {"status": "pass"}


@pytest.mark.parametrize(
    ("option", "value"),
    [("--root-collection", "Other/Scope"), ("--api-base", "http://example.invalid/api")],
)
def test_main_rejects_scope_and_api_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
) -> None:
    monkeypatch.setattr(
        sync_module.sys,
        "argv",
        [str(SCRIPT), "--vault-root", str(tmp_path), option, value],
    )

    with pytest.raises(SystemExit) as error:
        sync_module.main()

    assert error.value.code == 2
    assert option in capsys.readouterr().err

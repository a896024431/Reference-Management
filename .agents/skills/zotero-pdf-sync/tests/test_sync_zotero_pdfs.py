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
                    "title": "Root Standalone",
                }
                items.append(standalone)
            return items
        if "/collections/qpc/items/top" in path:
            return [{"key": "PAPER001", "data": {"itemType": "journalArticle", "title": "Paper A"}}]
        if "/collections/nested/items/top" in path:
            return [{"key": "PAPER002", "data": {"itemType": "journalArticle", "title": "Paper B"}}]
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
    assert index["items"]["ROOT0001"]["collection_path"] == ["未分类"]
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
                "version": sync_module.INDEX_VERSION,
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

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)

    assert not legacy_dir.exists()
    assert (vault / "文献" / "未分类" / "Root Paper" / "source-main.pdf").is_file()
    assert len(result["moved_directories"]) == 1


def test_maps_root_standalone_pdf_to_uncategorized_directory(fake_api: FakeApi) -> None:
    fake_api.include_root_standalone = True

    collected = papers(fake_api)
    standalone = next(paper for paper in collected if paper["key"] == "ROOTPDF1")

    assert standalone["collection"] == (sync_module.UNCATEGORIZED_COLLECTION,)
    assert standalone["title"] == "Root Standalone"


def test_sanitizes_windows_device_names_without_losing_pdf_extension() -> None:
    assert sync_module._safe_name("CON.pdf", "fallback.pdf") == "CON_.pdf"


def test_first_sync_and_unchanged_refresh(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    first = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    paper_dir = vault / "文献" / "QPC" / "Paper A"

    assert sorted(path.name for path in paper_dir.glob("*.pdf")) == ["source-main.pdf", "source-si.pdf"]
    assert len(first["copied"]) == 2
    assert (vault / ".local" / "zotero-pdf-sync" / "index.json").is_file()

    second = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    assert len(second["unchanged"]) == 2
    assert second["copied"] == []


def test_changed_pdf_is_protected_when_paper_has_note(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    destination = vault / "文献" / "QPC" / "Paper A" / "source-main.pdf"
    original = destination.read_bytes()
    (destination.parent / "笔记.md").write_text("note", encoding="utf-8")
    fake_api.main.write_bytes(b"main-v2")

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)

    assert destination.read_bytes() == original
    assert len(result["protected_pdfs"]) == 1
    assert result["stale_attachments"] == []
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))
    assert "MAIN0001" in index["items"]["PAPER001"]["attachments"]


def test_move_without_note_follows_collection_rename(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    old_dir = vault / "文献" / "QPC" / "Paper A"
    fake_api.collection_name = "QPC Updated"

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)

    assert not old_dir.exists()
    assert (vault / "文献" / "QPC Updated" / "Paper A" / "source-main.pdf").is_file()
    assert len(result["moved_directories"]) == 1


def test_changed_pdf_refreshes_hash_without_a_note(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    fake_api.main.write_bytes(b"main-v2")

    result = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    destination = vault / "文献" / "QPC" / "Paper A" / "source-main.pdf"
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))

    assert destination.read_bytes() == b"main-v2"
    assert len(result["copied"]) == 1
    assert index["items"]["PAPER001"]["attachments"]["MAIN0001"]["sha256"] == sync_module._sha256(
        destination
    )


def test_move_with_note_is_reported_and_keeps_its_index(fake_api: FakeApi, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    old_dir = vault / "文献" / "QPC" / "Paper A"
    (old_dir / "笔记.md").write_text("note", encoding="utf-8")
    fake_api.collection_name = "QPC Updated"

    first = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    second = sync_module.sync(vault, papers(fake_api), "http://fake/api", "ZJU/课题组", False)
    index = json.loads((vault / ".local" / "zotero-pdf-sync" / "index.json").read_text(encoding="utf-8"))

    assert old_dir.is_dir()
    assert not (vault / "文献" / "QPC Updated" / "Paper A").exists()
    assert len(first["protected_moves"]) == len(second["protected_moves"]) == 1
    assert index["items"]["PAPER001"]["relative_dir"] == "文献/QPC/Paper A"


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
    assert len(list((vault / ".local" / "zotero-pdf-sync" / "reports").glob("*.json"))) == 2


def test_reports_but_does_not_delete_all_removed_pdf_attachments(
    fake_api: FakeApi, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    original = papers(fake_api)[0]
    sync_module.sync(vault, [original], "http://fake/api", "ZJU/课题组", False)
    removed = {**original, "attachments": []}

    result = sync_module.sync(vault, [removed], "http://fake/api", "ZJU/课题组", False, complete=True)

    assert len(result["stale_attachments"]) == 2
    assert (vault / "文献" / "QPC" / "Paper A" / "source-main.pdf").is_file()
    assert (vault / "文献" / "QPC" / "Paper A" / "source-si.pdf").is_file()


def test_disambiguates_duplicate_attachment_filenames(tmp_path: Path) -> None:
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

    sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)

    assert sorted(path.name for path in (vault / "文献" / "QPC" / "Paper A").glob("*.pdf")) == [
        "article [ATTACH002].pdf",
        "article.pdf",
    ]


def test_disambiguates_same_title_paper_directories(tmp_path: Path) -> None:
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

    sync_module.sync(vault, papers_to_sync, "http://fake/api", "ZJU/课题组", False)

    assert (vault / "文献" / "QPC" / "Same title [PAPER001]" / "first.pdf").is_file()
    assert (vault / "文献" / "QPC" / "Same title [PAPER002]" / "second.pdf").is_file()


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

    assert (vault / "文献" / "QPC" / "Paper A" / "Zotero attachment name.pdf").is_file()


def test_preserves_an_unmanaged_pdf_with_the_same_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    paper_dir = vault / "文献" / "QPC" / "Paper A"
    paper_dir.mkdir(parents=True)
    existing = paper_dir / "article.pdf"
    existing.write_bytes(b"keep")
    source = tmp_path / "article.pdf"
    source.write_bytes(b"from-zotero")
    paper = paper_record("PAPER001", "Paper A", [file_record("ATTACH001", source)])

    sync_module.sync(vault, [paper], "http://fake/api", "ZJU/课题组", False)

    assert existing.read_bytes() == b"keep"
    assert (paper_dir / "article [ATTACH001].pdf").read_bytes() == b"from-zotero"


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

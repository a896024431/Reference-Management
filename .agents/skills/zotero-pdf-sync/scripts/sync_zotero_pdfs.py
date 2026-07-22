#!/usr/bin/env python3
"""Manually mirror PDF attachments from Zotero Local API into an Obsidian vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


API_BASE = "http://127.0.0.1:23119/api"
ROOT_COLLECTION = "ZJU/课题组"
LIBRARY = "文献"
UNCATEGORIZED_COLLECTION = "未分类"
ARCHIVE_COLLECTION = "Zotero已删除"
INDEX_VERSION = 2
ZOTERO_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
WINDOWS_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)


class SyncError(RuntimeError):
    pass


def _zotero_key(value: object, *, label: str) -> str:
    key = str(value or "").strip()
    if not key or not ZOTERO_KEY_PATTERN.fullmatch(key):
        raise SyncError(f"{label} 缺少或包含不安全的 Zotero key：{key!r}")
    return key


def _open(request: urllib.request.Request) -> Any:
    """Reach the loopback-only Local API without inheriting a system HTTP proxy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=15)


def _json_request(base: str, path: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/{path.lstrip('/')}",
        method="GET",
        headers={"Zotero-API-Version": "3", "Accept": "application/json"},
    )
    try:
        with _open(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SyncError(
                "Zotero Local API 被拒绝。请在 Zotero 设置 → 高级中允许本机应用访问。"
            ) from exc
        raise SyncError(f"Zotero Local API 请求失败：HTTP {exc.code} ({path})") from exc
    except urllib.error.URLError as exc:
        raise SyncError("Zotero Local API 不可用。请启动 Zotero 并开启 Local API。") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"Zotero Local API 返回了无效 JSON：{path}") from exc
    if not isinstance(payload, list):
        raise SyncError(f"Zotero Local API 返回了错误的数据结构：{path}")
    return [item for item in payload if isinstance(item, dict)]


def _text_request(base: str, path: str) -> str:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/{path.lstrip('/')}",
        method="GET",
        headers={"Zotero-API-Version": "3"},
    )
    try:
        with _open(request) as response:
            return response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SyncError(
                "Zotero Local API 被拒绝。请在 Zotero 设置 → 高级中允许本机应用访问。"
            ) from exc
        raise SyncError(f"Zotero 本地文件路径请求失败：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SyncError("Zotero Local API 不可用。") from exc


def _safe_name(value: str, fallback: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(". ")
    base, separator, extension = value.partition(".")
    if base.casefold() in WINDOWS_DEVICE_NAMES:
        value = f"{base}_{separator}{extension}"
    return value or fallback


def _visible_name(value: object, *, label: str) -> str:
    """Return a real user-visible name; never fall back to a Zotero key."""
    raw = str(value or "").strip()
    safe = _safe_name(raw, "")
    if not safe:
        raise SyncError(f"{label} 为空或无法作为 Windows 文件名使用")
    return safe


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_url_path(value: str) -> Path:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme.casefold() != "file" or parsed.netloc not in {"", "localhost"}:
        raise SyncError(f"Zotero 未提供可用的本地文件 URL：{value}")
    path = Path(urllib.request.url2pathname(urllib.parse.unquote(parsed.path))).resolve()
    if not path.is_file() or path.suffix.casefold() != ".pdf":
        raise SyncError(f"Zotero 附件不是可读取的 PDF：{path}")
    return path


def _attachment_path(base: str, record: dict[str, Any]) -> Path:
    links = record.get("links")
    if isinstance(links, dict):
        enclosure = links.get("enclosure")
        if isinstance(enclosure, dict):
            href = str(enclosure.get("href", ""))
            if href.casefold().startswith("file:"):
                return _file_url_path(href)
    key = str(record.get("key", "")).strip()
    if not key:
        raise SyncError("PDF 附件缺少 Zotero key")
    url = _text_request(base, f"users/0/items/{urllib.parse.quote(key)}/file/view/url?v=3")
    return _file_url_path(url)


def _parts(value: str) -> tuple[str, ...]:
    result = tuple(part.strip() for part in value.replace("\\", "/").split("/") if part.strip())
    if not result:
        raise SyncError("Zotero 分类路径不能为空")
    return result


def _collections(base: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for record in _json_request(base, "users/0/collections?format=json&v=3"):
        data = record.get("data")
        key = str(record.get("key", "")).strip()
        if not key or not isinstance(data, dict) or data.get("deleted"):
            continue
        name = str(data.get("name", "")).strip()
        parent = data.get("parentCollection", "")
        if name:
            result[key] = {"name": name, "parent": parent if isinstance(parent, str) else ""}
    return result


def _collection_key(collections: dict[str, dict[str, str]], path: tuple[str, ...]) -> str:
    parent = ""
    for name in path:
        matches = [
            key for key, data in collections.items() if data["name"] == name and data["parent"] == parent
        ]
        if len(matches) != 1:
            raise SyncError(f"Zotero 分类路径不存在或不唯一：{'/'.join(path)}")
        parent = matches[0]
    return parent


def _descendants(collections: dict[str, dict[str, str]], key: str) -> list[str]:
    children: dict[str, list[str]] = {}
    for child, data in collections.items():
        children.setdefault(data["parent"], []).append(child)
    result: list[str] = []

    def visit(current: str) -> None:
        result.append(current)
        for child in sorted(children.get(current, []), key=lambda item: (collections[item]["name"].casefold(), item)):
            visit(child)

    visit(key)
    return result


def _relative_collection(
    collections: dict[str, dict[str, str]], root: str, collection: str
) -> tuple[str, ...]:
    names: list[str] = []
    current = collection
    while current != root:
        data = collections.get(current)
        if data is None or not data["parent"]:
            raise SyncError("文献条目不在已配置的 Zotero 根分类中")
        names.append(
            _visible_name(data["name"], label=f"Zotero 分类 {current} 的名称")
        )
        current = data["parent"]
    relative = tuple(reversed(names)) or (UNCATEGORIZED_COLLECTION,)
    if relative[0].casefold() == ARCHIVE_COLLECTION.casefold():
        raise SyncError(f"{ARCHIVE_COLLECTION} 是 Vault 的保留归档目录名，不能作为 Zotero 一级分类")
    return relative


def _paper_folder(title: str) -> str:
    return _visible_name(title, label="论文题名")


def _is_pdf(record: dict[str, Any]) -> bool:
    data = record.get("data")
    return bool(
        isinstance(data, dict)
        and not data.get("deleted")
        and data.get("itemType") == "attachment"
        and str(data.get("contentType", "")).casefold() == "application/pdf"
    )


def _collect_papers(
    base: str, root_path: str, collection_scope: str, item_key: str
) -> list[dict[str, Any]]:
    collections = _collections(base)
    root = _collection_key(collections, _parts(root_path))
    selected = root
    if collection_scope:
        selected = _collection_key(collections, _parts(root_path) + _parts(collection_scope))
    selected_collections = set(_descendants(collections, selected))
    parent_items: dict[str, tuple[dict[str, Any], str]] = {}
    standalone: dict[str, tuple[dict[str, Any], str]] = {}
    memberships: dict[str, set[str]] = {}
    # Inspect the configured root even for a scoped refresh. Zotero permits an
    # item to belong to multiple collections, while this mirror has one stable
    # directory per parent key.
    for collection in _descendants(collections, root):
        endpoint = f"users/0/collections/{urllib.parse.quote(collection)}/items/top?format=json&v=3"
        for record in _json_request(base, endpoint):
            data = record.get("data")
            if not isinstance(data, dict) or data.get("deleted"):
                continue
            key = _zotero_key(record.get("key"), label="Zotero 条目")
            if _is_pdf(record) and not str(data.get("parentItem", "")).strip():
                memberships.setdefault(key, set()).add(collection)
                if collection in selected_collections:
                    standalone[key] = (record, collection)
            elif data.get("itemType") not in {"attachment", "note"}:
                memberships.setdefault(key, set()).add(collection)
                if collection in selected_collections:
                    parent_items[key] = (record, collection)
    requested_key = _zotero_key(item_key, label="--item-key") if item_key else ""
    if requested_key and requested_key not in parent_items and requested_key not in standalone:
        raise SyncError(f"在 {root_path} 中未找到 Zotero 条目 {item_key}")

    papers: list[dict[str, Any]] = []
    for key, (record, collection) in sorted(parent_items.items()):
        if requested_key and key != requested_key:
            continue
        if len(memberships.get(key, set())) != 1:
            raise SyncError(f"条目 {key} 同时属于多个 Zotero 分类；请先保留一个分类再同步")
        children = _json_request(base, f"users/0/items/{urllib.parse.quote(key)}/children?format=json&v=3")
        attachments = [child for child in children if _is_pdf(child)]
        title = _visible_name(record["data"].get("title", ""), label=f"文献条目 {key} 的题名")
        papers.append(
            {
                "key": key,
                "title": title,
                "collection": _relative_collection(collections, root, collection),
                "attachments": attachments,
            }
        )
    for key, (record, collection) in sorted(standalone.items()):
        if requested_key and key != requested_key:
            continue
        if len(memberships.get(key, set())) != 1:
            raise SyncError(f"独立 PDF {key} 同时属于多个 Zotero 分类；请先保留一个分类再同步")
        source = _attachment_path(base, record)
        raw_title = str(record["data"].get("title", "")).strip()
        raw_filename = str(record["data"].get("filename", "")).strip()
        fallback_title = Path(raw_filename).stem if raw_filename else source.stem
        title = _visible_name(
            raw_title or fallback_title,
            label=f"独立 PDF {key} 的题名",
        )
        if not raw_title and title.casefold() == key.casefold():
            raise SyncError(f"独立 PDF {key} 缺少可见题名，不能用 Zotero key 作为论文目录名")
        papers.append(
            {
                "key": key,
                "title": title,
                "collection": _relative_collection(collections, root, collection),
                "attachments": [record],
            }
        )
    return sorted(papers, key=lambda item: (item["collection"], item["title"].casefold(), item["key"]))


def _filename(value: object, *, label: str) -> str:
    name = str(value or "").strip()
    if (
        not name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
        or Path(name).suffix.casefold() != ".pdf"
    ):
        raise SyncError(f"同步索引中的 {label} 文件名无效：{name!r}")
    return name


def _stored_directory_component(value: object, *, label: str) -> str:
    """Validate a canonical visible path component saved in the local index."""
    if not isinstance(value, str):
        raise SyncError(f"同步索引中的 {label} 无效")
    normalized = _visible_name(value, label=f"同步索引中的 {label}")
    if value != normalized:
        raise SyncError(f"同步索引中的 {label} 未使用规范可见名称：{value!r}")
    return normalized


def _stored_collection_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SyncError("同步索引中的 collection_parts 无效")
    parts = tuple(
        _stored_directory_component(part, label=f"collection_parts[{index}]")
        for index, part in enumerate(value)
    )
    if not parts:
        raise SyncError("同步索引中的 collection_parts 不能为空")
    if parts and parts[0].casefold() == ARCHIVE_COLLECTION.casefold():
        raise SyncError(f"同步索引中的 collection_parts 不能指向 {ARCHIVE_COLLECTION}")
    return parts


def _index_item(value: object, *, parent_key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncError(f"同步索引中的条目 {parent_key} 无效")
    relative_dir = value.get("relative_dir")
    attachments = value.get("attachments")
    if not isinstance(relative_dir, str) or not isinstance(attachments, dict):
        raise SyncError(f"同步索引中的条目 {parent_key} 格式无效")
    collection_parts = _stored_collection_parts(value.get("collection_parts"))
    folder_name = _stored_directory_component(value.get("folder_name"), label="folder_name")
    normalized: dict[str, dict[str, str]] = {}
    for raw_key, raw_attachment in attachments.items():
        attachment_key = _zotero_key(raw_key, label="附件")
        if not isinstance(raw_attachment, dict):
            raise SyncError(f"同步索引中的附件 {attachment_key} 无效")
        normalized[attachment_key] = {
            "filename": _filename(raw_attachment.get("filename"), label="附件")
        }
    result: dict[str, Any] = {
        "relative_dir": relative_dir,
        "collection_parts": collection_parts,
        "folder_name": folder_name,
        "attachments": normalized,
    }
    return result


def _migrate_v1_index(data: dict[str, Any]) -> dict[str, Any]:
    old_items = data.get("items")
    if not isinstance(old_items, dict):
        raise SyncError("同步索引格式不受支持")
    items: dict[str, Any] = {}
    for raw_parent_key, raw_item in old_items.items():
        parent_key = _zotero_key(raw_parent_key, label="条目")
        if not isinstance(raw_item, dict):
            raise SyncError(f"同步索引中的条目 {parent_key} 无效")
        relative_dir = raw_item.get("relative_dir")
        old_attachments = raw_item.get("attachments")
        if not isinstance(relative_dir, str) or not isinstance(old_attachments, dict):
            raise SyncError(f"同步索引中的条目 {parent_key} 格式无效")
        folder_name = _visible_name(raw_item.get("title", ""), label=f"旧版条目 {parent_key} 的题名")
        raw_collection_parts = raw_item.get("collection_path", [])
        if not isinstance(raw_collection_parts, list):
            raise SyncError(f"旧版条目 {parent_key} 的 collection_path 无效")
        collection_parts = tuple(
            _visible_name(part, label=f"旧版条目 {parent_key} 的分类")
            for part in raw_collection_parts
        )
        if collection_parts and collection_parts[0].casefold() == ARCHIVE_COLLECTION.casefold():
            raise SyncError(f"旧版条目 {parent_key} 指向保留归档目录")
        attachments: dict[str, dict[str, str]] = {}
        for raw_attachment_key, raw_attachment in old_attachments.items():
            attachment_key = _zotero_key(raw_attachment_key, label="附件")
            if not isinstance(raw_attachment, dict):
                raise SyncError(f"同步索引中的附件 {attachment_key} 无效")
            relative_path = raw_attachment.get("relative_path")
            if not isinstance(relative_path, str) or "\\" in relative_path:
                raise SyncError(f"同步索引中的附件路径无效：{relative_path!r}")
            attachments[attachment_key] = {
                "filename": _filename(relative_path.rsplit("/", maxsplit=1)[-1], label="附件")
            }
        item: dict[str, Any] = {
            "relative_dir": relative_dir,
            "collection_parts": collection_parts,
            "folder_name": folder_name,
            "attachments": attachments,
        }
        items[parent_key] = item
    return {"version": INDEX_VERSION, "items": items, "migrated_from_v1": True}


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": INDEX_VERSION, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"同步索引无法读取：{path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        raise SyncError(f"同步索引格式不受支持：{path}")
    if data.get("version") == 1:
        return _migrate_v1_index(data)
    if data.get("version") != INDEX_VERSION:
        raise SyncError(f"同步索引格式不受支持：{path}")
    items = {
        _zotero_key(parent_key, label="条目"): _index_item(item, parent_key=str(parent_key))
        for parent_key, item in data["items"].items()
    }
    return {"version": INDEX_VERSION, "items": items}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy(source: Path, destination: Path, source_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.sync-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        if _sha256(temporary) != source_hash:
            raise SyncError(f"复制后的 PDF 哈希不一致：{source.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _retire_replaced_attachment(old_path: Path, destination: Path) -> None:
    """Remove an obsolete attachment without deleting a Windows case-only rename."""
    if not old_path.is_file():
        return
    try:
        same_file = destination.is_file() and old_path.samefile(destination)
    except OSError:
        same_file = False
    case_only_rename = (
        same_file
        and old_path.name != destination.name
        and old_path.name.casefold() == destination.name.casefold()
    )
    if not case_only_rename:
        old_path.unlink()
        return

    # NTFS treats the two spellings as one directory entry.  Rename through a
    # fresh sibling so the requested spelling is retained without unlinking
    # the just-copied PDF.
    temporary = old_path.with_name(f".{old_path.name}.rename-{uuid.uuid4().hex}")
    os.replace(old_path, temporary)
    try:
        os.replace(temporary, destination)
    except OSError:
        if temporary.exists() and not old_path.exists():
            os.replace(temporary, old_path)
        raise


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _from_relative(vault: Path, value: str, *, label: str) -> Path:
    """Resolve an index path and reject paths that could escape the vault."""
    if not value or "\\" in value:
        raise SyncError(f"同步索引中的 {label} 路径无效：{value!r}")
    parts = tuple(part for part in value.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise SyncError(f"同步索引中的 {label} 路径无效：{value!r}")
    candidate = (vault / Path(*parts)).resolve()
    try:
        candidate.relative_to(vault)
    except ValueError as exc:
        raise SyncError(f"同步索引中的 {label} 路径超出 Vault：{value!r}") from exc
    return candidate


def _managed_directory(
    vault: Path,
    item: dict[str, Any],
    *,
    label: str,
    allow_legacy_v1_shallow: bool = False,
) -> Path:
    value = item["relative_dir"]
    directory = _from_relative(vault, value, label=label)
    library = (vault / LIBRARY).resolve()
    try:
        directory.relative_to(library)
    except ValueError as exc:
        raise SyncError(f"同步索引中的 {label} 不在文献目录下：{value!r}") from exc
    collection_parts = tuple(item["collection_parts"])
    folder_name = str(item["folder_name"])
    if not collection_parts:
        if not allow_legacy_v1_shallow:
            raise SyncError(f"同步索引中的 {label} 不是 文献/<分类>/<论文目录>：{value!r}")
        expected = (library / folder_name).resolve()
    else:
        expected = library.joinpath(*collection_parts, folder_name).resolve()
    if directory != expected:
        raise SyncError(
            f"同步索引中的 {label} 与受管理论文目录身份不一致：{value!r}"
        )
    return directory


def _archive_destination(vault: Path, source: Path) -> Path:
    library = (vault / LIBRARY).resolve()
    relative = source.resolve().relative_to(library)
    base = library / ARCHIVE_COLLECTION / Path(*relative.parts)
    candidate = base
    attempt = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name} [archived-{attempt}]")
        attempt += 1
    return candidate


def _attachment_filename(source: Path, key: str, zotero_filename: str) -> str:
    original = _visible_name(zotero_filename or source.name, label=f"附件 {key} 的文件名")
    if Path(original).suffix.casefold() != ".pdf":
        original = _visible_name(source.name, label=f"附件 {key} 的本地文件名")
    if not zotero_filename and Path(original).stem.casefold() == key.casefold():
        raise SyncError(f"附件 {key} 缺少可见文件名，不能用 Zotero key 作为本地文件名")
    return _filename(original, label="附件")


def _attachment_specs(base: str, paper_key: str, attachments: list[Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    keys: set[str] = set()
    for record in sorted(
        attachments,
        key=lambda item: str(item.get("key", "")).casefold() if isinstance(item, dict) else "",
    ):
        if not isinstance(record, dict):
            raise SyncError(f"文献条目 {paper_key} 包含无效附件")
        attachment_key = _zotero_key(record.get("key"), label=f"文献条目 {paper_key} 的 PDF 附件")
        if attachment_key in keys:
            raise SyncError(f"文献条目 {paper_key} 的 PDF 附件 key 重复：{attachment_key}")
        keys.add(attachment_key)
        source = _attachment_path(base, record)
        data = record.get("data")
        zotero_filename = str(data.get("filename", "")).strip() if isinstance(data, dict) else ""
        specs.append(
            {
                "key": attachment_key,
                "source": source,
                "source_hash": _sha256(source),
                "filename": _attachment_filename(source, attachment_key, zotero_filename),
            }
        )
    return specs


def _empty_directory(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def sync(
    vault_root: Path,
    papers: list[dict[str, Any]],
    base: str,
    root_collection: str,
    dry_run: bool,
    *,
    complete: bool = False,
) -> dict[str, Any]:
    vault = vault_root.expanduser().resolve()
    if not vault.is_dir():
        raise SyncError(f"Vault 根目录不是目录：{vault}")
    library = vault / LIBRARY
    local = vault / ".local" / "zotero-pdf-sync"
    index_path = local / "index.json"
    loaded_index = _load_index(index_path)
    old_items = loaded_index["items"]
    allow_legacy_v1_shallow = bool(loaded_index.get("migrated_from_v1"))
    if allow_legacy_v1_shallow and any(
        not item["collection_parts"] for item in old_items.values()
    ) and not complete:
        raise SyncError("旧版浅层同步索引只能在一次完整同步中迁移")
    owned_directories: dict[str, str] = {}
    for parent_key, item in old_items.items():
        directory = _managed_directory(
            vault,
            item,
            label="论文目录",
            allow_legacy_v1_shallow=allow_legacy_v1_shallow,
        )
        relative = _relative(directory, vault)
        marker = relative.casefold()
        previous_owner = owned_directories.get(marker)
        if previous_owner and previous_owner != parent_key:
            raise SyncError(
                f"同步索引中的条目 {previous_owner} 和 {parent_key} 指向同一论文目录：{relative}"
            )
        owned_directories[marker] = parent_key
    desired_target_owners: dict[str, list[str]] = {}
    preflight_keys: set[str] = set()
    for paper in papers:
        paper_key = _zotero_key(paper.get("key"), label="文献条目")
        if paper_key in preflight_keys:
            raise SyncError(f"同步结果包含重复 Zotero 条目：{paper_key}")
        preflight_keys.add(paper_key)
        raw_collection = paper.get("collection")
        if not isinstance(raw_collection, (list, tuple)) or not raw_collection:
            raise SyncError(f"文献条目 {paper_key} 的分类路径无效")
        collection = tuple(_safe_name(str(part), "分类") for part in raw_collection)
        if collection[0].casefold() == ARCHIVE_COLLECTION.casefold():
            raise SyncError(f"{ARCHIVE_COLLECTION} 是保留归档目录，不能作为同步目标")
        title = _visible_name(paper.get("title", ""), label=f"文献条目 {paper_key} 的题名")
        folder_name = _paper_folder(title)
        marker = _relative(library.joinpath(*collection, folder_name), vault).casefold()
        desired_target_owners.setdefault(marker, []).append(paper_key)
    same_title_targets = {
        marker: sorted(keys) for marker, keys in desired_target_owners.items() if len(keys) > 1
    }
    report: dict[str, Any] = {
        "status": "pass",
        "root_collection": root_collection,
        "dry_run": dry_run,
        "complete": complete,
        "copied": [],
        "unchanged": [],
        "moved_directories": [],
        "renamed_attachments": [],
        "deleted_attachments": [],
        "archived_directories": [],
        "directory_conflicts": [],
        "file_conflicts": [],
        "archive_missing_directories": [],
    }
    # A collection or single-item refresh must not discard records outside its scope.
    new_items: dict[str, Any] = dict(old_items)
    seen_items: set[str] = set()
    for paper in papers:
        paper_key = _zotero_key(paper.get("key"), label="文献条目")
        if paper_key in seen_items:
            raise SyncError(f"同步结果包含重复 Zotero 条目：{paper_key}")
        seen_items.add(paper_key)
        attachments = paper.get("attachments")
        if not isinstance(attachments, list):
            raise SyncError(f"文献条目 {paper_key} 的附件列表无效")
        raw_collection = paper.get("collection")
        if not isinstance(raw_collection, (list, tuple)) or not raw_collection:
            raise SyncError(f"文献条目 {paper_key} 的分类路径无效")
        collection = tuple(_safe_name(str(part), "分类") for part in raw_collection)
        if collection[0].casefold() == ARCHIVE_COLLECTION.casefold():
            raise SyncError(f"{ARCHIVE_COLLECTION} 是保留归档目录，不能作为同步目标")
        title = _visible_name(paper.get("title", ""), label=f"文献条目 {paper_key} 的题名")
        folder_name = _paper_folder(title)
        target = library.joinpath(*collection, folder_name)
        target_relative = _relative(target, vault)
        if target_relative.casefold() in same_title_targets:
            report["directory_conflicts"].append(
                {
                    "item_keys": same_title_targets[target_relative.casefold()],
                    "path": target_relative,
                    "reason": "same_title_directory",
                }
            )
            continue
        specs = _attachment_specs(base, paper_key, attachments)
        old = old_items.get(paper_key)
        if old is None and not specs:
            continue
        previous = old["attachments"] if old else {}
        old_relative = old["relative_dir"] if old else ""
        old_target = (
            _managed_directory(
                vault,
                old,
                label="论文目录",
                allow_legacy_v1_shallow=allow_legacy_v1_shallow,
            )
            if old
            else None
        )
        moving = bool(old_target and old_target != target and old_target.exists())

        if old_target and old_target != target and old_target.exists() and not old_target.is_dir():
            report["directory_conflicts"].append(
                {"item_key": paper_key, "from": old_relative, "to": target_relative}
            )
            continue
        if old_target and old_target != target and target.exists():
            report["directory_conflicts"].append(
                {"item_key": paper_key, "from": old_relative, "to": target_relative}
            )
            continue
        if old is None and target.exists():
            report["directory_conflicts"].append(
                {"item_key": paper_key, "path": target_relative, "reason": "unindexed_target_exists"}
            )
            continue
        inspection_target = old_target if moving and old_target is not None else target
        if inspection_target.exists() and not inspection_target.is_dir():
            report["directory_conflicts"].append(
                {"item_key": paper_key, "path": _relative(inspection_target, vault)}
            )
            continue

        previous_names = {
            entry["filename"].casefold(): attachment_key
            for attachment_key, entry in previous.items()
        }
        desired_keys = {str(spec["key"]) for spec in specs}
        desired_names: dict[str, str] = {}
        conflict = False
        for spec in specs:
            filename = str(spec["filename"])
            existing_key = desired_names.get(filename.casefold())
            if existing_key and existing_key != str(spec["key"]):
                report["file_conflicts"].append(
                    {
                        "item_key": paper_key,
                        "attachment_keys": sorted([existing_key, str(spec["key"])]),
                        "path": f"{target_relative}/{filename}",
                        "reason": "same_attachment_filename",
                    }
                )
                conflict = True
            desired_names[filename.casefold()] = filename
        if inspection_target.is_dir():
            for attachment_key, entry in previous.items():
                previous_path = inspection_target / entry["filename"]
                if previous_path.exists() and not previous_path.is_file():
                    report["file_conflicts"].append(
                        {
                            "item_key": paper_key,
                            "attachment_key": attachment_key,
                            "path": _relative(previous_path, vault),
                        }
                    )
                    conflict = True
        for spec in specs:
            attachment_key = str(spec["key"])
            existing_owner = previous_names.get(str(spec["filename"]).casefold())
            if existing_owner and existing_owner != attachment_key:
                report["file_conflicts"].append(
                    {
                        "item_key": paper_key,
                        "attachment_key": attachment_key,
                        "path": f"{target_relative}/{spec['filename']}",
                    }
                )
                conflict = True
            destination = inspection_target / str(spec["filename"])
            if destination.exists() and not destination.is_file():
                report["file_conflicts"].append(
                    {
                        "item_key": paper_key,
                        "attachment_key": attachment_key,
                        "path": f"{target_relative}/{spec['filename']}",
                    }
                )
                conflict = True
        if conflict:
            continue

        if moving:
            if dry_run:
                report["moved_directories"].append(
                    {"item_key": paper_key, "from": old_relative, "to": target_relative, "dry_run": True}
                )
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old_target, target)
                report["moved_directories"].append(
                    {"item_key": paper_key, "from": old_relative, "to": target_relative}
                )
        working_target = inspection_target if dry_run and moving else target
        attachment_index: dict[str, dict[str, str]] = {}
        for spec in specs:
            attachment_key = str(spec["key"])
            filename = str(spec["filename"])
            destination = working_target / filename
            destination_relative = f"{target_relative}/{filename}"
            source_hash = str(spec["source_hash"])
            previous_entry = previous.get(attachment_key)
            if destination.exists() and _sha256(destination) == source_hash:
                report["unchanged"].append(destination_relative)
            elif dry_run:
                report["copied"].append({"path": destination_relative, "dry_run": True})
            else:
                _copy(Path(spec["source"]), destination, source_hash)
                report["copied"].append(destination_relative)
            if previous_entry and previous_entry["filename"] != filename:
                old_filename = previous_entry["filename"]
                old_path = working_target / old_filename
                if old_path.is_file():
                    if not dry_run:
                        _retire_replaced_attachment(old_path, destination)
                    renamed: dict[str, Any] = {
                        "item_key": paper_key,
                        "attachment_key": attachment_key,
                        "from": f"{target_relative}/{old_filename}",
                        "to": destination_relative,
                    }
                    if dry_run:
                        renamed["dry_run"] = True
                    report["renamed_attachments"].append(renamed)
            attachment_index[attachment_key] = {"filename": filename}
        for attachment_key, previous_entry in previous.items():
            if attachment_key in desired_keys:
                continue
            old_path = working_target / previous_entry["filename"]
            if old_path.is_file():
                deleted: dict[str, Any] = {
                    "item_key": paper_key,
                    "attachment_key": attachment_key,
                    "path": f"{target_relative}/{previous_entry['filename']}",
                }
                if dry_run:
                    deleted["dry_run"] = True
                else:
                    old_path.unlink()
                report["deleted_attachments"].append(deleted)
        if working_target.is_dir():
            for local_pdf in working_target.iterdir():
                if (
                    local_pdf.is_file()
                    and local_pdf.suffix.casefold() == ".pdf"
                    and local_pdf.name.casefold() not in desired_names
                ):
                    deleted: dict[str, Any] = {
                        "item_key": paper_key,
                        "attachment_key": "",
                        "path": f"{target_relative}/{local_pdf.name}",
                        "reason": "not_in_zotero",
                    }
                    if dry_run:
                        deleted["dry_run"] = True
                    else:
                        local_pdf.unlink()
                    report["deleted_attachments"].append(deleted)
        if not dry_run and not specs and _empty_directory(target):
            target.rmdir()
        new_items[paper_key] = {
            "relative_dir": target_relative,
            "collection_parts": collection,
            "folder_name": folder_name,
            "attachments": attachment_index,
        }
    if complete:
        for paper_key, old in old_items.items():
            if paper_key in seen_items:
                continue
            old_target = _managed_directory(
                vault,
                old,
                label="论文目录",
                allow_legacy_v1_shallow=allow_legacy_v1_shallow,
            )
            if old_target.exists() and not old_target.is_dir():
                report["directory_conflicts"].append(
                    {"item_key": paper_key, "path": old["relative_dir"], "reason": "managed_path_not_directory"}
                )
                continue
            if old_target.is_dir():
                archive_target = _archive_destination(vault, old_target)
                archive_relative = _relative(archive_target, vault)
                if dry_run:
                    report["archived_directories"].append(
                        {
                            "item_key": paper_key,
                            "from": old["relative_dir"],
                            "to": archive_relative,
                            "dry_run": True,
                        }
                    )
                else:
                    archive_target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old_target, archive_target)
                    report["archived_directories"].append(
                        {"item_key": paper_key, "from": old["relative_dir"], "to": archive_relative}
                    )
            else:
                report["archive_missing_directories"].append(
                    {"item_key": paper_key, "path": old["relative_dir"]}
                )
            new_items.pop(paper_key, None)
    if any(not item["collection_parts"] for item in new_items.values()):
        raise SyncError(
            "旧版浅层同步索引未完成迁移；请处理冲突后重新执行一次完整同步"
        )
    if any(
        report[key]
        for key in ("directory_conflicts", "file_conflicts", "archive_missing_directories")
    ):
        report["status"] = "attention"
    report["summary"] = {key: len(value) for key, value in report.items() if isinstance(value, list)}
    if not dry_run:
        now = datetime.now(timezone.utc)
        _write_json(index_path, {"version": INDEX_VERSION, "updated_at": now.isoformat(), "items": new_items})
        report_path = local / "reports" / f"sync-{now.strftime('%Y%m%dT%H%M%S.%fZ')}.json"
        _write_json(report_path, report)
        report["report_path"] = _relative(report_path, vault)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--collection", default="")
    source.add_argument("--item-key", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        papers = _collect_papers(API_BASE, ROOT_COLLECTION, args.collection, args.item_key)
        result = sync(
            Path(args.vault_root),
            papers,
            API_BASE,
            ROOT_COLLECTION,
            args.dry_run,
            complete=not args.collection and not args.item_key,
        )
    except SyncError as exc:
        print(json.dumps({"status": "fail", "failures": [str(exc)]}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    except OSError as exc:
        print(
            json.dumps({"status": "fail", "failures": [f"文件系统错误：{exc}"]}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

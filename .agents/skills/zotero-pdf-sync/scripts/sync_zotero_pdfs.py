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
INDEX_VERSION = 1
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
        names.append(_safe_name(data["name"], current))
        current = data["parent"]
    return tuple(reversed(names)) or (UNCATEGORIZED_COLLECTION,)


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
    parent_items: dict[str, tuple[dict[str, Any], str]] = {}
    standalone: dict[str, tuple[dict[str, Any], str]] = {}
    for collection in _descendants(collections, selected):
        endpoint = f"users/0/collections/{urllib.parse.quote(collection)}/items/top?format=json&v=3"
        for record in _json_request(base, endpoint):
            data = record.get("data")
            key = str(record.get("key", "")).strip()
            if not key or not isinstance(data, dict) or data.get("deleted"):
                continue
            if _is_pdf(record) and not str(data.get("parentItem", "")).strip():
                previous = standalone.get(key)
                if previous and previous[1] != collection:
                    raise SyncError(f"独立 PDF {key} 同时属于多个目标分类")
                standalone[key] = (record, collection)
            elif data.get("itemType") not in {"attachment", "note"}:
                previous = parent_items.get(key)
                if previous and previous[1] != collection:
                    raise SyncError(f"条目 {key} 同时属于多个目标分类，需要用户决定")
                parent_items[key] = (record, collection)
    if item_key and item_key not in parent_items and item_key not in standalone:
        raise SyncError(f"在 {root_path} 中未找到 Zotero 条目 {item_key}")

    papers: list[dict[str, Any]] = []
    for key, (record, collection) in sorted(parent_items.items()):
        if item_key and key != item_key:
            continue
        children = _json_request(base, f"users/0/items/{urllib.parse.quote(key)}/children?format=json&v=3")
        attachments = [child for child in children if _is_pdf(child)]
        title = _safe_name(str(record["data"].get("title", "")), key)
        papers.append(
            {
                "key": key,
                "title": title,
                "collection": _relative_collection(collections, root, collection),
                "attachments": attachments,
            }
        )
    for key, (record, collection) in sorted(standalone.items()):
        if item_key and key != item_key:
            continue
        source = _attachment_path(base, record)
        title = _safe_name(str(record["data"].get("title", "")) or source.stem, key)
        papers.append(
            {
                "key": key,
                "title": title,
                "collection": _relative_collection(collections, root, collection),
                "attachments": [record],
            }
        )
    return sorted(papers, key=lambda item: (item["collection"], item["title"].casefold(), item["key"]))


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": INDEX_VERSION, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"同步索引无法读取：{path}") from exc
    if not isinstance(data, dict) or data.get("version") != INDEX_VERSION or not isinstance(data.get("items"), dict):
        raise SyncError(f"同步索引格式不受支持：{path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.sync-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        if _sha256(temporary) != _sha256(source):
            raise SyncError(f"复制后的 PDF 哈希不一致：{source.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


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


def _attachment_entry(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    path = value.get("relative_path")
    digest = value.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str):
        return None
    return {"relative_path": path, "sha256": digest}


def _report_stale_attachment(
    report: dict[str, Any], vault: Path, item_key: str, attachment_key: str, value: Any
) -> None:
    entry = _attachment_entry(value)
    if entry is None:
        return
    path = _from_relative(vault, entry["relative_path"], label="附件")
    if path.is_file():
        report["stale_attachments"].append(
            {"item_key": item_key, "attachment_key": attachment_key, "path": entry["relative_path"]}
        )


def _indexed_attachment_uses_name(previous: dict[str, Any], key: str, filename: str) -> bool:
    entry = _attachment_entry(previous.get(key))
    if entry is None:
        return False
    return entry["relative_path"].rsplit("/", maxsplit=1)[-1].casefold() == filename.casefold()


def _attachment_filename(
    source: Path,
    key: str,
    names: set[str],
    target: Path,
    previous: dict[str, Any],
    zotero_filename: str,
) -> str:
    original = _safe_name(zotero_filename or source.name, f"{key}.pdf")
    if Path(original).suffix.casefold() != ".pdf":
        original = _safe_name(source.name, f"{key}.pdf")
    suffix = Path(original).suffix or ".pdf"
    stem = original[: -len(suffix)] if suffix else original
    attempt = 0
    while True:
        if attempt == 0:
            filename = original
        elif attempt == 1:
            filename = f"{stem} [{key}]{suffix}"
        else:
            filename = f"{stem} [{key}]-{attempt - 1}{suffix}"
        destination = target / filename
        known = _indexed_attachment_uses_name(previous, key, filename)
        if filename.casefold() not in names and (not destination.exists() or known):
            names.add(filename.casefold())
            return filename
        attempt += 1


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
    old_items = _load_index(index_path)["items"]
    groups: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = {}
    for paper in papers:
        groups.setdefault((tuple(paper["collection"]), paper["title"]), []).append(paper)
    folders = {
        paper["key"]: _safe_name(paper["title"], paper["key"])
        + (f" [{paper['key']}]" if len(groups[(tuple(paper['collection']), paper['title'])]) > 1 else "")
        for paper in papers
    }
    report: dict[str, Any] = {
        "status": "pass",
        "root_collection": root_collection,
        "dry_run": dry_run,
        "complete": complete,
        "copied": [],
        "unchanged": [],
        "moved_directories": [],
        "protected_moves": [],
        "protected_pdfs": [],
        "directory_conflicts": [],
        "file_conflicts": [],
        "stale_attachments": [],
    }
    # A collection or single-item refresh must not discard records outside its scope.
    new_items: dict[str, Any] = dict(old_items)
    seen_items: set[str] = set()
    for paper in papers:
        paper_key = str(paper.get("key", "")).strip()
        if not paper_key:
            raise SyncError("文献条目缺少 Zotero key")
        seen_items.add(paper_key)
        attachments = paper.get("attachments")
        if not isinstance(attachments, list):
            raise SyncError(f"文献条目 {paper_key} 的附件列表无效")
        target = library.joinpath(*paper["collection"], folders[paper_key])
        target_relative = _relative(target, vault)
        old = old_items.get(paper_key, {})
        previous = old.get("attachments", {}) if isinstance(old, dict) else {}
        previous = previous if isinstance(previous, dict) else {}
        old_relative_value = old.get("relative_dir") if isinstance(old, dict) else ""
        old_relative = old_relative_value if isinstance(old_relative_value, str) else ""
        if not attachments:
            if isinstance(old, dict):
                for attachment_key, value in previous.items():
                    _report_stale_attachment(report, vault, paper_key, str(attachment_key), value)
            continue
        if old_relative and old_relative != target_relative:
            old_target = _from_relative(vault, old_relative, label="论文目录")
            if old_target.exists() and (old_target / "笔记.md").exists():
                report["protected_moves"].append(
                    {"item_key": paper_key, "from": old_relative, "to": target_relative}
                )
                # Keep the local paper path stable and continue refreshing its attachments there.
                target = old_target
                target_relative = old_relative
            elif old_target.exists() and target.exists():
                report["directory_conflicts"].append(
                    {"item_key": paper_key, "from": old_relative, "to": target_relative}
                )
                continue
            elif old_target.exists():
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
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
        attachment_index: dict[str, dict[str, str]] = {}
        attachment_names: set[str] = set()
        for record in sorted(
            attachments,
            key=lambda item: str(item.get("key", "")).casefold() if isinstance(item, dict) else "",
        ):
            if not isinstance(record, dict):
                raise SyncError(f"文献条目 {paper_key} 包含无效附件")
            key = str(record.get("key", "")).strip()
            if not key:
                raise SyncError(f"文献条目 {paper_key} 的 PDF 附件缺少 Zotero key")
            source = _attachment_path(base, record)
            data = record.get("data")
            zotero_filename = str(data.get("filename", "")).strip() if isinstance(data, dict) else ""
            filename = _attachment_filename(
                source, key, attachment_names, target, previous, zotero_filename
            )
            destination = target / filename
            destination_relative = _relative(destination, vault)
            source_hash = _sha256(source)
            previous_entry = _attachment_entry(previous.get(key))
            if destination.exists() and not destination.is_file():
                report["file_conflicts"].append(
                    {"item_key": paper_key, "attachment_key": key, "path": destination_relative}
                )
                if previous_entry is not None:
                    attachment_index[key] = previous_entry
                continue
            if destination.exists() and _sha256(destination) == source_hash:
                report["unchanged"].append(destination_relative)
            elif destination.exists() and (target / "笔记.md").exists():
                report["protected_pdfs"].append(
                    {"item_key": paper_key, "attachment_key": key, "path": destination_relative}
                )
                attachment_index[key] = previous_entry or {
                    "relative_path": destination_relative,
                    "sha256": _sha256(destination),
                }
                continue
            elif dry_run:
                report["copied"].append({"path": destination_relative, "dry_run": True})
            else:
                _copy(source, destination)
                report["copied"].append(destination_relative)
            attachment_index[key] = {"relative_path": destination_relative, "sha256": source_hash}
        for attachment_key, value in previous.items():
            old_entry = _attachment_entry(value)
            current_entry = _attachment_entry(attachment_index.get(str(attachment_key)))
            if old_entry is None:
                continue
            if current_entry is None or current_entry["relative_path"] != old_entry["relative_path"]:
                _report_stale_attachment(report, vault, paper_key, str(attachment_key), old_entry)
        new_items[paper_key] = {
            "title": paper["title"],
            "collection_path": list(paper["collection"]),
            "relative_dir": target_relative,
            "attachments": attachment_index,
        }
    if complete:
        for paper_key, old in old_items.items():
            if str(paper_key) in seen_items or not isinstance(old, dict):
                continue
            previous = old.get("attachments")
            if not isinstance(previous, dict):
                continue
            for attachment_key, value in previous.items():
                _report_stale_attachment(report, vault, str(paper_key), str(attachment_key), value)
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
    parser.add_argument("--root-collection", default=ROOT_COLLECTION)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--collection", default="")
    source.add_argument("--item-key", default="")
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        papers = _collect_papers(args.api_base, args.root_collection, args.collection, args.item_key)
        result = sync(
            Path(args.vault_root),
            papers,
            args.api_base,
            args.root_collection,
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

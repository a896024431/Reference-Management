from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else REPO_ROOT / ".local" / "config.toml"
    if not path.exists() or tomllib is None:
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def resolve_zotero_data_dir(value: str | None = None, config_path: str | Path | None = None) -> Path:
    if value:
        data_dir = Path(value).expanduser()
    elif os.environ.get("ZOTERO_DATA_DIR"):
        data_dir = Path(os.environ["ZOTERO_DATA_DIR"]).expanduser()
    else:
        config = load_config(config_path)
        data_dir = Path(config.get("zotero", {}).get("data_dir", "")).expanduser()

    if not str(data_dir):
        raise FileNotFoundError("Zotero data directory is not configured.")
    if not (data_dir / "zotero.sqlite").exists():
        raise FileNotFoundError(f"Missing zotero.sqlite under: {data_dir}")
    return data_dir.resolve()


@contextlib.contextmanager
def connect_snapshot(zotero_data_dir: Path) -> Iterator[sqlite3.Connection]:
    with tempfile.TemporaryDirectory(prefix="zotero-snapshot-") as temp_dir:
        source = zotero_data_dir / "zotero.sqlite"
        snapshot = Path(temp_dir) / "zotero.sqlite"
        shutil.copy2(source, snapshot)
        conn = sqlite3.connect(snapshot)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def deleted_filter(conn: sqlite3.Connection, alias: str = "i") -> str:
    if table_exists(conn, "deletedItems"):
        return f" AND {alias}.itemID NOT IN (SELECT itemID FROM deletedItems)"
    return ""


def get_item_by_key(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    sql = f"""
        SELECT i.itemID, i.key, i.dateAdded, i.dateModified, t.typeName
        FROM items i
        LEFT JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
        WHERE i.key = ? {deleted_filter(conn, "i")}
    """
    return row_dict(conn.execute(sql, (key,)).fetchone())


def find_item_by_title(conn: sqlite3.Connection, title_fragment: str) -> dict[str, Any] | None:
    sql = f"""
        SELECT i.itemID, i.key, i.dateAdded, i.dateModified, t.typeName
        FROM items i
        LEFT JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
        JOIN itemData d ON i.itemID = d.itemID
        JOIN fields f ON d.fieldID = f.fieldID
        JOIN itemDataValues v ON d.valueID = v.valueID
        WHERE f.fieldName = 'title' AND v.value LIKE ? {deleted_filter(conn, "i")}
        ORDER BY i.dateModified DESC
        LIMIT 1
    """
    return row_dict(conn.execute(sql, (f"%{title_fragment}%",)).fetchone())


def get_metadata(conn: sqlite3.Connection, item_id: int) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT f.fieldName, v.value
        FROM itemData d
        JOIN fields f ON d.fieldID = f.fieldID
        JOIN itemDataValues v ON d.valueID = v.valueID
        WHERE d.itemID = ?
        """,
        (item_id,),
    ).fetchall()
    return {row["fieldName"]: row["value"] for row in rows}


def get_creators(conn: sqlite3.Connection, item_id: int) -> list[dict[str, Any]]:
    if not table_exists(conn, "itemCreators") or not table_exists(conn, "creators"):
        return []
    creator_cols = table_columns(conn, "creators")
    select_parts = ["ic.orderIndex"]
    if table_exists(conn, "creatorTypes"):
        select_parts.append("ct.creatorType")
        join_creator_type = "LEFT JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID"
    else:
        select_parts.append("NULL AS creatorType")
        join_creator_type = ""
    for col in ("firstName", "lastName", "fieldMode", "name"):
        if col in creator_cols:
            select_parts.append(f"c.{col}")
        else:
            select_parts.append(f"NULL AS {col}")
    sql = f"""
        SELECT {", ".join(select_parts)}
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        {join_creator_type}
        WHERE ic.itemID = ?
        ORDER BY ic.orderIndex
    """
    creators = []
    for row in conn.execute(sql, (item_id,)).fetchall():
        data = row_dict(row) or {}
        if data.get("name"):
            display_name = data["name"]
        else:
            display_name = " ".join(
                part for part in [data.get("firstName"), data.get("lastName")] if part
            ).strip()
        data["display_name"] = display_name
        creators.append(data)
    return creators


def get_collections_for_item(conn: sqlite3.Connection, item_id: int) -> list[dict[str, Any]]:
    if not table_exists(conn, "collectionItems"):
        return []
    key_select = "c.key" if "key" in table_columns(conn, "collections") else "NULL AS key"
    rows = conn.execute(
        f"""
        SELECT c.collectionID, {key_select}, c.collectionName
        FROM collectionItems ci
        JOIN collections c ON ci.collectionID = c.collectionID
        WHERE ci.itemID = ?
        ORDER BY c.collectionName
        """,
        (item_id,),
    ).fetchall()
    return [row_dict(row) or {} for row in rows]


def resolve_storage_path(zotero_data_dir: Path, attachment_key: str, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    if raw_path.startswith("storage:"):
        return zotero_data_dir / "storage" / attachment_key / raw_path.removeprefix("storage:")
    raw = Path(raw_path)
    if raw.is_absolute():
        return raw
    return zotero_data_dir / raw_path


def get_attachments(conn: sqlite3.Connection, zotero_data_dir: Path, item_id: int) -> list[dict[str, Any]]:
    if not table_exists(conn, "itemAttachments"):
        return []
    attachment_cols = table_columns(conn, "itemAttachments")
    selected_cols = [f"ia.{col}" for col in sorted(attachment_cols)]
    rows = conn.execute(
        f"""
        SELECT i.key AS attachmentKey, {", ".join(selected_cols)}
        FROM itemAttachments ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE ia.parentItemID = ?
        ORDER BY ia.itemID
        """,
        (item_id,),
    ).fetchall()
    attachments = []
    for row in rows:
        data = row_dict(row) or {}
        path = resolve_storage_path(zotero_data_dir, data["attachmentKey"], data.get("path"))
        data["resolved_path"] = str(path) if path else ""
        data["exists"] = bool(path and path.exists())
        if data["attachmentKey"]:
            data["select_link"] = f"zotero://select/library/items/{data['attachmentKey']}"
            data["pdf_link"] = f"zotero://open-pdf/library/items/{data['attachmentKey']}"
        attachments.append(data)
    return attachments


def get_annotations(conn: sqlite3.Connection, item_id: int, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not table_exists(conn, "itemAnnotations"):
        return []
    parent_ids = [item_id]
    for attachment in attachments:
        if attachment.get("itemID") is not None:
            parent_ids.append(int(attachment["itemID"]))
    placeholders = ",".join("?" for _ in parent_ids)
    annotation_cols = table_columns(conn, "itemAnnotations")
    selected_cols = [f"ia.{col}" for col in sorted(annotation_cols)]
    rows = conn.execute(
        f"""
        SELECT i.key AS annotationKey, {", ".join(selected_cols)}
        FROM itemAnnotations ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE ia.parentItemID IN ({placeholders})
        ORDER BY ia.parentItemID, ia.sortIndex
        """,
        parent_ids,
    ).fetchall()
    return [row_dict(row) or {} for row in rows]


def get_notes(conn: sqlite3.Connection, item_id: int) -> list[dict[str, Any]]:
    if not table_exists(conn, "itemNotes"):
        return []
    note_cols = table_columns(conn, "itemNotes")
    selected_cols = [f"n.{col}" for col in sorted(note_cols)]
    rows = conn.execute(
        f"""
        SELECT i.key AS noteKey, {", ".join(selected_cols)}
        FROM itemNotes n
        JOIN items i ON n.itemID = i.itemID
        WHERE n.parentItemID = ?
        ORDER BY n.itemID
        """,
        (item_id,),
    ).fetchall()
    return [row_dict(row) or {} for row in rows]


def read_fulltext_caches(attachments: list[dict[str, Any]], max_chars: int = 60000) -> list[dict[str, Any]]:
    caches = []
    for attachment in attachments:
        path_value = attachment.get("resolved_path")
        if not path_value:
            continue
        cache_path = Path(path_value).parent / ".zotero-ft-cache"
        if not cache_path.exists():
            continue
        text = cache_path.read_text(encoding="utf-8", errors="replace")
        caches.append(
            {
                "attachmentKey": attachment.get("attachmentKey", ""),
                "cache_path": str(cache_path),
                "text": text[:max_chars],
                "truncated": len(text) > max_chars,
            }
        )
    return caches


def extract_item(
    conn: sqlite3.Connection,
    zotero_data_dir: Path,
    item_key: str | None = None,
    title: str | None = None,
    max_cache_chars: int = 60000,
) -> dict[str, Any]:
    item = get_item_by_key(conn, item_key) if item_key else None
    if item is None and title:
        item = find_item_by_title(conn, title)
    if item is None:
        raise LookupError("No Zotero item matched the supplied key or title.")

    item_id = int(item["itemID"])
    metadata = get_metadata(conn, item_id)
    creators = get_creators(conn, item_id)
    collections = get_collections_for_item(conn, item_id)
    attachments = get_attachments(conn, zotero_data_dir, item_id)
    annotations = get_annotations(conn, item_id, attachments)
    notes = get_notes(conn, item_id)
    fulltext = read_fulltext_caches(attachments, max_chars=max_cache_chars)

    item["select_link"] = f"zotero://select/library/items/{item['key']}"
    result = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "item": item,
        "metadata": metadata,
        "creators": creators,
        "collections": collections,
        "attachments": attachments,
        "annotations": annotations,
        "notes": notes,
        "fulltext": fulltext,
    }
    result["raw_data_buffer"] = build_raw_data_buffer(result)
    return result


def build_raw_data_buffer(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {})
    creators = ", ".join(c.get("display_name", "") for c in data.get("creators", []) if c.get("display_name"))
    lines = [
        "# Raw_Data_Buffer",
        "",
        "## Metadata",
        f"- Title: {metadata.get('title', '')}",
        f"- Authors: {creators}",
        f"- Year/Date: {metadata.get('date', '')}",
        f"- Publication: {metadata.get('publicationTitle') or metadata.get('conferenceName') or ''}",
        f"- DOI: {metadata.get('DOI', '')}",
        f"- Zotero Key: {data.get('item', {}).get('key', '')}",
        "",
        "## Abstract",
        metadata.get("abstractNote", ""),
        "",
        "## Annotations",
    ]
    for annotation in data.get("annotations", []):
        page = annotation.get("pageLabel") or annotation.get("pageIndex") or ""
        text = annotation.get("text") or annotation.get("comment") or ""
        if text:
            lines.append(f"- Page {page}: {text}")
    lines.extend(["", "## Notes"])
    for note in data.get("notes", []):
        if note.get("note"):
            lines.append(str(note["note"]))
    lines.extend(["", "## Full Text Cache"])
    for cache in data.get("fulltext", []):
        lines.append(f"### Attachment {cache.get('attachmentKey', '')}")
        lines.append(cache.get("text", ""))
    return "\n".join(lines).strip() + "\n"


def safe_filename(value: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:180] or fallback


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

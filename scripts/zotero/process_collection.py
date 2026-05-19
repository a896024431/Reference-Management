from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from zotero_db import (
    REPO_ROOT,
    connect_snapshot,
    deleted_filter,
    extract_item,
    resolve_zotero_data_dir,
    safe_filename,
    write_json,
)


DONE_RE = re.compile(r"\|\s*(?:✅ 成功|⚠️ 跳过)\s*\|\s*([A-Za-z0-9]+)\s*\|")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare raw buffers for pending Zotero collection items.")
    parser.add_argument("--collection", required=True, help="Zotero collection name")
    parser.add_argument("--zotero-data-dir", help="Path containing zotero.sqlite")
    parser.add_argument("--vault-root", default=".", help="Vault root, default current repository")
    parser.add_argument("--notes-dir", default="note")
    parser.add_argument("--raw-dir", default=".local/raw")
    parser.add_argument("--config", help="Optional .local/config.toml path")
    parser.add_argument("--limit", type=int, default=0, help="Maximum pending items to fetch; 0 means all")
    parser.add_argument("--dry-run", action="store_true", help="Only print pending items")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary")
    return parser.parse_args()


def collection_items(conn, collection_name: str) -> list[dict[str, Any]]:
    row = conn.execute(
        "SELECT collectionID, collectionName FROM collections WHERE collectionName = ? ORDER BY collectionID LIMIT 1",
        (collection_name,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Collection not found: {collection_name}")
    rows = conn.execute(
        f"""
        SELECT
            i.itemID,
            i.key,
            t.typeName,
            (
                SELECT v.value
                FROM itemData d
                JOIN fields f ON d.fieldID = f.fieldID
                JOIN itemDataValues v ON d.valueID = v.valueID
                WHERE d.itemID = i.itemID AND f.fieldName = 'title'
                LIMIT 1
            ) AS title,
            ci.orderIndex
        FROM collectionItems ci
        JOIN items i ON ci.itemID = i.itemID
        LEFT JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
        WHERE ci.collectionID = ? {deleted_filter(conn, "i")}
        ORDER BY ci.orderIndex, title
        """,
        (row["collectionID"],),
    ).fetchall()
    return [dict(item) for item in rows]


def process_log_path(vault_root: Path, notes_dir: str, collection_name: str) -> Path:
    return vault_root / notes_dir / safe_filename(collection_name, "collection") / "_ProcessLog_进度记录.md"


def read_completed_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    return {match.group(1) for match in DONE_RE.finditer(text)}


def ensure_process_log(path: Path, collection_name: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(
        f"# {collection_name} 处理进度\n\n> Created {now}. `✅ 成功` 和 `⚠️ 跳过` 会在下次运行时跳过。\n\n",
        encoding="utf-8",
    )


def pending_items(items: list[dict[str, Any]], completed_keys: set[str]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("key") not in completed_keys]


def main() -> int:
    args = parse_args()
    vault_root = Path(args.vault_root).resolve()
    data_dir = resolve_zotero_data_dir(args.zotero_data_dir, args.config)
    log_path = process_log_path(vault_root, args.notes_dir, args.collection)
    ensure_process_log(log_path, args.collection)
    completed = read_completed_keys(log_path)

    with connect_snapshot(data_dir) as conn:
        items = collection_items(conn, args.collection)
        pending = pending_items(items, completed)
        if args.limit > 0:
            pending = pending[: args.limit]

        summary = {
            "collection": args.collection,
            "total": len(items),
            "completed": len(completed),
            "pending": len(pending),
            "process_log": str(log_path),
            "items": pending,
        }

        if args.dry_run:
            if args.json:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                print(f"Collection: {args.collection}")
                print(f"Total: {len(items)}")
                print(f"Pending: {len(pending)}")
                for item in pending:
                    print(f"- {item.get('key')} | {item.get('title') or '(untitled)'}")
            return 0

        raw_root = (REPO_ROOT / args.raw_dir / safe_filename(args.collection, "collection")).resolve()
        written = []
        for item in pending:
            result = extract_item(conn, data_dir, item_key=item["key"])
            result["target_collection"] = args.collection
            output_path = raw_root / f"{item['key']}.json"
            write_json(output_path, result)
            written.append(str(output_path))

    print(json.dumps({**summary, "raw_files": written}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

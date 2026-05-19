from __future__ import annotations

import argparse
import json
from pathlib import Path

from zotero_db import connect_snapshot, extract_item, resolve_zotero_data_dir, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Zotero item metadata and raw text as JSON.")
    parser.add_argument("--item-key", help="Zotero item key, e.g. ABCD1234")
    parser.add_argument("--title", help="Fallback title fragment search")
    parser.add_argument("--zotero-data-dir", help="Path containing zotero.sqlite")
    parser.add_argument("--config", help="Optional .local/config.toml path")
    parser.add_argument("--output", help="Write JSON to this path instead of stdout")
    parser.add_argument("--max-cache-chars", type=int, default=60000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.item_key and not args.title:
        raise SystemExit("Provide --item-key or --title.")

    data_dir = resolve_zotero_data_dir(args.zotero_data_dir, args.config)
    with connect_snapshot(data_dir) as conn:
        result = extract_item(
            conn,
            data_dir,
            item_key=args.item_key,
            title=args.title,
            max_cache_chars=args.max_cache_chars,
        )

    if args.output:
        write_json(Path(args.output), result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

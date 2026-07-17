#!/usr/bin/env python3
"""Split a v2 corpus inventory into one explicit JSON input record per paper."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--corpus", required=True)
    command.add_argument("--output-dir", required=True)
    return command


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized[:96] or "paper"


def main() -> None:
    args = parser().parse_args()
    corpus = json.loads(Path(args.corpus).expanduser().resolve().read_text(encoding="utf-8"))
    records = corpus.get("records")
    if corpus.get("schema_version") != "2.0" or not isinstance(records, list):
        raise SystemExit("Expected a schema-v2 corpus inventory")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, str]] = []
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not str(record.get("title", "")).strip():
            raise SystemExit(f"Invalid record at position {position}")
        name = f"{position:02d}-{slug(str(record['title']))}.json"
        target = output_dir / name
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index.append({"title": str(record["title"]), "input_record": str(target)})
    (output_dir / "index.json").write_text(
        json.dumps({"schema_version": "2.0", "records": index}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps({"record_count": len(index), "output_dir": str(output_dir)}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()

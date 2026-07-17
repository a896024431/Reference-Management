#!/usr/bin/env python3
"""Create a reversible, hash-addressed snapshot of the vault's Research tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--vault-root", default=".", help="Obsidian vault root.")
    command.add_argument(
        "--output",
        help=(
            "Snapshot directory. Defaults to .local/deeppapernote/migration-backup/<UTC timestamp>."
        ),
    )
    return command


def main() -> None:
    args = parser().parse_args()
    vault_root = Path(args.vault_root).expanduser().resolve()
    research = (vault_root / "Research").resolve()
    if not research.is_dir() or research.parent != vault_root:
        raise SystemExit(f"Research directory not found directly under vault root: {research}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else vault_root / ".local" / "deeppapernote" / "migration-backup" / timestamp
    )
    if output == research or research in output.parents:
        raise SystemExit("Snapshot output must not be inside Research.")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Snapshot output is not empty: {output}")

    snapshot_research = output / "Research"
    snapshot_research.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(research, snapshot_research, dirs_exist_ok=False)

    files = []
    for path in sorted(snapshot_research.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "path": path.relative_to(snapshot_research).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "vault_root": str(vault_root),
        "source": "Research",
        "file_count": len(files),
        "files": files,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"snapshot": str(output), "file_count": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Conservatively configure local Obsidian settings for DeepPaperNote v2."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_IGNORE_FILTERS = (r"^\.local/", r"^tmp/", r"^DeepPaperNote_output/")
RECENT_EXCLUDED_PREFIXES = (".local/", "tmp/", "deeppapernote_output/")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "configure Obsidian for DeepPaperNote v2")
    p.add_argument("--vault", default=".", help="Obsidian vault root (default: current directory).")
    p.add_argument(
        "--clean-recent",
        action="store_true",
        help=(
            "Remove only .local/, tmp/, and DeepPaperNote_output/ entries "
            "from workspace lastOpenFiles."
        ),
    )
    p.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    p.add_argument("--output", default="", help="Optional JSON status path.")
    return p


def load_json_object(
    path: Path, *, missing_default: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if not path.exists():
        return dict(missing_default or {})
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def merge_ignore_filters(
    config: Mapping[str, Any],
    required_filters: tuple[str, ...] = DEFAULT_IGNORE_FILTERS,
) -> tuple[dict[str, Any], list[str]]:
    """Merge required regexes without changing any other app setting."""
    merged = dict(config)
    existing = merged.get("userIgnoreFilters", [])
    if existing is None:
        existing = []
    if not isinstance(existing, list) or any(not isinstance(item, str) for item in existing):
        raise ValueError(".obsidian/app.json userIgnoreFilters must be a list of strings")

    updated = list(existing)
    seen = {item.casefold() for item in existing}
    added: list[str] = []
    for pattern in required_filters:
        if pattern.casefold() in seen:
            continue
        updated.append(pattern)
        seen.add(pattern.casefold())
        added.append(pattern)
    merged["userIgnoreFilters"] = updated
    return merged, added


def is_generated_recent_path(value: str) -> bool:
    normalized = value.strip().replace("\\", "/").lstrip("/").casefold()
    return any(normalized.startswith(prefix) for prefix in RECENT_EXCLUDED_PREFIXES)


def clean_recent_files(workspace: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove generated paths only from the top-level Obsidian recent-file list."""
    cleaned = dict(workspace)
    existing = cleaned.get("lastOpenFiles", [])
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        raise ValueError(".obsidian/workspace.json lastOpenFiles must be a list")
    removed = [
        item for item in existing if isinstance(item, str) and is_generated_recent_path(item)
    ]
    cleaned["lastOpenFiles"] = [
        item for item in existing if not (isinstance(item, str) and is_generated_recent_path(item))
    ]
    return cleaned, removed


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.deeppapernote-v2.tmp")
    temporary.write_text(_json_text(value), encoding="utf-8")
    temporary.replace(path)


def _backup_file(path: Path, backup_root: Path) -> str:
    if not path.exists():
        return ""
    backup_root.mkdir(parents=True, exist_ok=True)
    destination = backup_root / path.name
    shutil.copy2(path, destination)
    return str(destination)


def configure_obsidian(
    vault_root: Path,
    *,
    clean_recent: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    vault_root = vault_root.expanduser().resolve()
    obsidian_dir = vault_root / ".obsidian"
    app_path = obsidian_dir / "app.json"
    workspace_path = obsidian_dir / "workspace.json"

    app_before = load_json_object(app_path)
    app_after, added_filters = merge_ignore_filters(app_before)
    app_changed = app_before != app_after

    workspace_before: dict[str, Any] | None = None
    workspace_after: dict[str, Any] | None = None
    removed_recent: list[str] = []
    workspace_changed = False
    if clean_recent and workspace_path.exists():
        workspace_before = load_json_object(workspace_path)
        workspace_after, removed_recent = clean_recent_files(workspace_before)
        workspace_changed = workspace_before != workspace_after

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = vault_root / ".local" / "deeppapernote" / "obsidian-config-backups" / timestamp
    backups: list[str] = []
    if not dry_run:
        if app_changed:
            backup = _backup_file(app_path, backup_root)
            if backup:
                backups.append(backup)
            _atomic_write_json(app_path, app_after)
        if workspace_changed and workspace_after is not None:
            backup = _backup_file(workspace_path, backup_root)
            if backup:
                backups.append(backup)
            _atomic_write_json(workspace_path, workspace_after)

    return {
        "schema_version": "2.0",
        "status": "dry_run" if dry_run else "ok",
        "vault": str(vault_root),
        "app_json": str(app_path),
        "app_changed": app_changed,
        "added_ignore_filters": added_filters,
        "workspace_json": str(workspace_path),
        "workspace_changed": workspace_changed,
        "removed_recent_files": removed_recent,
        "backups": backups,
    }


def main() -> None:
    args = parser().parse_args()
    result = configure_obsidian(
        Path(args.vault),
        clean_recent=args.clean_recent,
        dry_run=args.dry_run,
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()

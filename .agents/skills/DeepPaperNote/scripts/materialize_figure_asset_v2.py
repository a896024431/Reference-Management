#!/usr/bin/env python3
"""Materialize only explicitly inserted, manifest-verified figure assets."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    emit,
    maybe_load_json_record,
    resolve_domain_subdir,
    resolve_note_output_mode,
    resolve_obsidian_note_path,
    runtime_config,
)
from contracts_v2 import SCHEMA_VERSION
from figure_contracts_v2 import FigureContractError, materialize_decision


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "materialize figure asset v2")
    p.add_argument("--manifest", required=True, help="figure_manifest.json path or JSON string.")
    p.add_argument("--decisions", required=True, help="figure_decisions.json path or JSON string.")
    p.add_argument("--target-id", required=True, help="Decision target_id marked as inserted.")
    p.add_argument("--destination-dir", default="", help="Explicit destination image directory.")
    p.add_argument("--input", default="", help="Optional metadata/paper-record JSON.")
    p.add_argument("--title", default="")
    p.add_argument("--vault", default="")
    p.add_argument("--subdir", default="")
    p.add_argument("--filename", default="")
    p.add_argument("--asset-subdir", default="images")
    p.add_argument("--label", default="")
    p.add_argument("--output", default="")
    return p


def main() -> None:
    args = parser().parse_args()
    manifest = maybe_load_json_record(args.manifest)
    decisions = maybe_load_json_record(args.decisions)
    if not isinstance(manifest, dict) or not isinstance(decisions, dict):
        raise SystemExit(
            "materialize_figure_asset_v2.py requires valid manifest and decisions JSON."
        )

    record = maybe_load_json_record(args.input) or {}
    title = args.title or str(record.get("title", "")).strip()
    note_path: Path | None = None
    output_mode = "directory"
    root_path: Path | None = None
    if args.destination_dir:
        destination_dir = Path(args.destination_dir).expanduser().resolve()
    else:
        if not title:
            raise SystemExit("Provide --destination-dir, or --title/metadata for vault resolution.")
        config = runtime_config()
        if args.vault:
            config["obsidian_vault"] = args.vault
        resolved_subdir = resolve_domain_subdir(
            config,
            title=title,
            abstract=str(record.get("abstract", "")),
            subdir=args.subdir,
        )
        note_path = resolve_obsidian_note_path(
            config,
            title=title,
            subdir=resolved_subdir,
            filename=args.filename,
        )
        destination_dir = note_path.parent / args.asset_subdir
        output_mode, root_path = resolve_note_output_mode(config)

    try:
        materialized = materialize_decision(
            manifest=manifest,
            decisions=decisions,
            target_id=args.target_id,
            destination_dir=destination_dir,
        )
    except FigureContractError as exc:
        raise SystemExit(f"Figure materialization refused: {exc}") from exc

    destination = Path(materialized["dest_image_path"])
    relative_embed = f"![{args.label or materialized['label']}]({destination.name})"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "failures": [],
        "script": "materialize_figure_asset_v2.py",
        **materialized,
        "title": title,
        "note_path": str(note_path) if note_path else "",
        "output_mode": output_mode,
        "relative_markdown_embed": relative_embed,
    }
    if note_path is not None:
        relative_from_note = destination.relative_to(note_path.parent).as_posix()
        payload["relative_markdown_embed"] = (
            f"![{args.label or materialized['label']}]({relative_from_note})"
        )
    if output_mode == "obsidian" and root_path is not None:
        vault_relative = destination.relative_to(root_path).as_posix()
        payload["vault_relative_image_path"] = vault_relative
        payload["obsidian_embed"] = f"![[{vault_relative}]]"
    emit(payload, args.output)


if __name__ == "__main__":
    main()

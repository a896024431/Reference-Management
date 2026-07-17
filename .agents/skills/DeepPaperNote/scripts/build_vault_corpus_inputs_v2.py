#!/usr/bin/env python3
"""Build explicit, offline v2 input records for every paper already in a vault."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

FIELD_ALIASES = {
    "title_zh": ("标题翻译", "中文标题"),
    "authors": ("作者",),
    "year": ("年份",),
    "date": ("发表时间", "日期"),
    "venue": ("会议 / 期刊", "场所"),
    "doi": ("DOI",),
    "source_url": ("论文链接",),
    "arxiv": ("arXiv",),
}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--vault-root", default=".")
    command.add_argument("--literature-dir", default="文献")
    command.add_argument(
        "--output",
        default=".local/deeppapernote/migration-inputs/corpus.json",
    )
    return command


def normalize_title(value: str) -> str:
    text = value.casefold().replace("atomic force microscope", "afm")
    text = text.replace("fabry–pérot", "fabry perot").replace("fabry-pérot", "fabry perot")
    text = re.sub(r"^\(si\)\s*", "", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _frontmatter(note: str) -> dict[str, Any]:
    if not note.startswith("---\n"):
        return {}
    end = note.find("\n---\n", 4)
    if end < 0:
        return {}
    block = note[4:end]
    result: dict[str, Any] = {}
    current_list = ""
    for raw in block.splitlines():
        item = re.match(r"^\s+-\s+[\"']?(.*?)[\"']?\s*$", raw)
        if item and current_list:
            result.setdefault(current_list, []).append(item.group(1))
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", raw)
        if not match:
            continue
        key, value = match.groups()
        current_list = key if not value else ""
        if value:
            result[key] = value.strip("\"'")
        elif current_list:
            result[key] = []
    return result


def _core_fields(note: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    section = re.search(r"(?ms)^## 核心信息\s*\n(.*?)(?=^## |\Z)", note)
    if not section:
        return result
    lines: dict[str, str] = {}
    for key, value in re.findall(r"(?m)^-\s+([^:：]+)\s*[:：]\s*(.*?)\s*$", section.group(1)):
        lines[key.strip()] = value.strip()
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if lines.get(alias):
                result[target] = lines[alias]
                break
    authors = str(result.get("authors", ""))
    if authors:
        separator = ";" if ";" in authors else ","
        result["authors"] = [item.strip() for item in authors.split(separator) if item.strip()]
    date = str(result.get("date", ""))
    if not result.get("year") and re.match(r"^\d{4}", date):
        result["year"] = date[:4]
    source = str(result.get("source_url", ""))
    urls = re.findall(r"https?://\S+", source)
    if urls:
        result["source_url"] = urls[0].rstrip(";,")
    elif source:
        result.pop("source_url", None)
    return result


def _match_pdf(title: str, pdfs: list[Path]) -> tuple[Path, list[Path], float]:
    main_pdfs = [path for path in pdfs if not path.stem.casefold().startswith("(si)")]
    if not main_pdfs:
        raise ValueError("literature directory has no main PDF")
    normalized_title = normalize_title(title)
    ranked = sorted(
        (
            (SequenceMatcher(None, normalized_title, normalize_title(path.stem)).ratio(), path)
            for path in main_pdfs
        ),
        reverse=True,
        key=lambda item: item[0],
    )
    score, main = ranked[0]
    normalized_main = normalize_title(main.stem)
    supplements = [
        path
        for path in pdfs
        if path.stem.casefold().startswith("(si)")
        and SequenceMatcher(None, normalized_main, normalize_title(path.stem)).ratio() >= 0.75
    ]
    return main, sorted(supplements), score


def build_corpus(vault_root: Path, literature_dir: str) -> dict[str, Any]:
    vault_root = vault_root.expanduser().resolve()
    research = vault_root / "Research"
    literature = vault_root / literature_dir
    pdfs = sorted(literature.rglob("*.pdf"))
    records: list[dict[str, Any]] = []
    used_main: set[Path] = set()
    for paper_dir in sorted(path for path in research.iterdir() if path.is_dir()):
        note_path = paper_dir / "笔记.md"
        if not note_path.is_file():
            continue
        note = note_path.read_text(encoding="utf-8-sig")
        yaml = _frontmatter(note)
        core = _core_fields(note)
        main, supplements, score = _match_pdf(paper_dir.name, pdfs)
        if score < 0.7:
            raise ValueError(
                f"Low-confidence PDF match for {paper_dir.name}: {main.name} ({score:.3f})"
            )
        if main in used_main:
            raise ValueError(f"Main PDF matched more than once: {main}")
        used_main.add(main)
        record: dict[str, Any] = {
            "title": paper_dir.name,
            **core,
            "main_pdf": main.relative_to(vault_root).as_posix(),
            "supplement_pdfs": [path.relative_to(vault_root).as_posix() for path in supplements],
            "existing_note": note_path.relative_to(vault_root).as_posix(),
            "existing_aliases": yaml.get("aliases", []),
            "existing_tags": yaml.get("tags", []),
            "match_score": round(score, 6),
        }
        if yaml.get("doi") and not record.get("doi"):
            record["doi"] = yaml["doi"]
        if yaml.get("date") and not record.get("date"):
            record["date"] = yaml["date"]
            if re.match(r"^\d{4}", str(yaml["date"])):
                record.setdefault("year", str(yaml["date"])[:4])
        records.append(record)
    return {
        "schema_version": "2.0",
        "vault_root": str(vault_root),
        "paper_count": len(records),
        "main_document_count": len(records),
        "supplement_document_count": sum(len(item["supplement_pdfs"]) for item in records),
        "records": records,
    }


def main() -> None:
    args = parser().parse_args()
    vault_root = Path(args.vault_root).expanduser().resolve()
    corpus = build_corpus(vault_root, args.literature_dir)
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = vault_root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: corpus[key]
                for key in ("paper_count", "main_document_count", "supplement_document_count")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

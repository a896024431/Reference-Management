#!/usr/bin/env python3
"""Obsidian Vault v2 helpers for DeepPaperNote.

DeepPaperNote frontmatter is a small, documented YAML subset (top-level scalars
and lists), so validation does not need a permissive third-party YAML loader.
PyMuPDF is used only to prove that raster assets can actually be decoded.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import fitz
from contracts_v2 import SCHEMA_VERSION, sha256_file

NOTE_FILENAME = "\u7b14\u8bb0.md"
LOCAL_PDF_LIBRARY_ROOT = "\u6587\u732e"
PAPER_LIBRARY_PATH = Path(LOCAL_PDF_LIBRARY_ROOT)
NAVIGATION_PATH = PAPER_LIBRARY_PATH / "\u8bba\u6587\u5bfc\u822a.md"
BASE_PATH = PAPER_LIBRARY_PATH / "\u8bba\u6587\u5e93.base"
ZOTERO_DELETED_COLLECTION = "Zotero\u5df2\u5220\u9664"
ZOTERO_DELETED_PATH = PAPER_LIBRARY_PATH / ZOTERO_DELETED_COLLECTION

REQUIRED_PROPERTIES = (
    "type",
    "title",
    "title_zh",
    "authors",
    "year",
    "venue",
    "domain",
    "topics",
    "paper_type",
    "evidence_level",
    "note_status",
    "aliases",
    "tags",
)

OPTIONAL_PROPERTIES = (
    "date",
    "doi",
    "arxiv",
    "source_url",
    "local_pdf",
    "supplement_pdfs",
    "methods",
    "materials",
    "code_url",
    "project_url",
)

# Existing reader notes may retain this former output property. New notes do not
# write it, but legacy notes must not block navigation or Vault maintenance.
LEGACY_PROPERTIES = ("figure_status",)

LIST_PROPERTIES = {
    "authors",
    "topics",
    "aliases",
    "tags",
    "supplement_pdfs",
    "methods",
    "materials",
}

PROPERTY_ENUMS = {
    "type": {"paper"},
    "paper_type": {
        "experimental_physics",
        "theoretical_physics",
        "materials_fabrication",
        "ai_method",
        "benchmark",
        "clinical",
        "survey",
        "humanities",
        "generic",
    },
    "evidence_level": {"full_text", "full_text_supplement"},
    "note_status": {"draft", "reviewed", "polished", "degraded"},
    "figure_status": {"complete", "partial", "placeholder_only", "none_needed"},
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
TEMP_PATH_PARTS = (".local/", "tmp/", "deeppapernote_output/")
RUNTIME_STATUS_PATTERNS = (
    re.compile(r"\bzotero\s+not\s+available\b", re.IGNORECASE),
    re.compile(r"\bzotero\s+unavailable\b", re.IGNORECASE),
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]|\\\\[^\\\s]+[\\/][^\s]+|(?:^|[\s('`\"])/(?:Users|home)/[^\s)'`\"]+)"
)
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
REFERENCE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\s*\[[^\]]*\]")
SHORTCUT_IMAGE_RE = re.compile(r"!\[[^\[\]]+\](?!\s*[\[(])")
HTML_IMAGE_RE = re.compile(r"<img\b", re.IGNORECASE)
TAG_RE = re.compile(r"^papers(?:/[a-z0-9][a-z0-9-]*)+$")
YEAR_RE = re.compile(r"^(?:18|19|20|21)\d{2}$")
BASE_REQUIRED_VIEWS = (
    "\u5168\u90e8\u8bba\u6587",
    "\u6309\u4e3b\u9898",
)
BASE_REQUIRED_FILTERS = (
    f'file.inFolder("{LOCAL_PDF_LIBRARY_ROOT}")',
    f'!file.inFolder("{ZOTERO_DELETED_PATH.as_posix()}")',
    'file.name == "\u7b14\u8bb0"',
)


@dataclass(frozen=True)
class FrontmatterResult:
    properties: dict[str, Any]
    body: str
    errors: tuple[str, ...] = ()


@dataclass
class NoteRecord:
    path: Path
    relative_path: str
    folder_name: str
    properties: dict[str, Any]
    body: str
    title_heading: str
    parse_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkResolution:
    status: str
    path: Path | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class WikiLink:
    raw: str
    target: str
    embedded: bool


@dataclass
class VaultIssue:
    code: str
    path: str
    message: str
    severity: str = "error"
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class BaseDefinition:
    global_filters: tuple[str, ...]
    views: tuple[str, ...]


def _strip_yaml_comment(value: str) -> str:
    """Strip an unquoted YAML comment from a scalar."""
    quote = ""
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
            continue
        if char == "#" and not quote and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def _split_inline_list(value: str) -> list[str]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in inner:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            current.append(char)
            escaped = True
            continue
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
            current.append(char)
            continue
        if char == "," and not quote:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def _parse_scalar(value: str) -> Any:
    value = _strip_yaml_comment(value.strip())
    if value == "":
        return ""
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(item) for item in _split_inline_list(value)]
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    lowered = value.lower()
    if lowered in {"null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    # Dates, years and identifiers intentionally stay strings.
    return value


_BASE_TOP_LEVEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
_BASE_VIEW_ITEM_RE = re.compile(r"^  -\s+([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
_BASE_VIEW_NAME_RE = re.compile(r"^    name:(?:\s*(.*))?$")


def parse_base_definition(text: str) -> BaseDefinition:
    """Parse the structural subset of Obsidian Bases used by this Vault."""
    top_level: set[str] = set()
    global_filters: list[str] = []
    view_items: list[dict[str, str]] = []
    active_top_level = ""
    active_view: dict[str, str] | None = None

    for line_number, raw in enumerate(text.lstrip("\ufeff").splitlines(), start=1):
        if "\t" in raw:
            raise ValueError(f"tabs are not allowed at line {line_number}")
        line = _strip_yaml_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")

        if indent == 0:
            match = _BASE_TOP_LEVEL_RE.fullmatch(line)
            if not match:
                raise ValueError(f"invalid top-level Base line {line_number}")
            key = match.group(1)
            if key in top_level:
                raise ValueError(f"duplicate top-level Base key: {key}")
            top_level.add(key)
            active_top_level = key
            active_view = None
            continue

        if not active_top_level:
            raise ValueError(f"nested Base line without a parent at line {line_number}")

        if active_top_level == "filters" and stripped.startswith("- "):
            expression = _parse_scalar(stripped[2:].strip())
            if expression not in {None, ""}:
                global_filters.append(str(expression))
            continue

        if active_top_level != "views":
            continue

        item_match = _BASE_VIEW_ITEM_RE.fullmatch(line)
        if item_match:
            key = item_match.group(1)
            if key != "type":
                raise ValueError(f"Base view item must start with type at line {line_number}")
            view_type = str(_parse_scalar(item_match.group(2) or "")).strip()
            if not view_type:
                raise ValueError(f"Base view type is empty at line {line_number}")
            active_view = {"type": view_type, "name": ""}
            view_items.append(active_view)
            continue

        name_match = _BASE_VIEW_NAME_RE.fullmatch(line)
        if name_match:
            if active_view is None:
                raise ValueError(f"Base view name has no view at line {line_number}")
            if active_view["name"]:
                raise ValueError(f"duplicate Base view name at line {line_number}")
            name = str(_parse_scalar(name_match.group(1) or "")).strip()
            if not name:
                raise ValueError(f"Base view name is empty at line {line_number}")
            active_view["name"] = name

    missing_sections = [key for key in ("filters", "views") if key not in top_level]
    if missing_sections:
        raise ValueError(f"missing Base section(s): {', '.join(missing_sections)}")
    if not view_items:
        raise ValueError("Base views section is empty")
    incomplete = [view["type"] for view in view_items if not view["name"]]
    if incomplete:
        raise ValueError(f"Base view missing name: {', '.join(incomplete)}")

    view_names = tuple(view["name"] for view in view_items)
    duplicate_names = sorted(
        {name for name in view_names if view_names.count(name) > 1}, key=str.casefold
    )
    if duplicate_names:
        raise ValueError(f"duplicate Base view name(s): {', '.join(duplicate_names)}")
    return BaseDefinition(tuple(global_filters), view_names)


def parse_frontmatter(text: str) -> FrontmatterResult:
    normalized = text.lstrip("\ufeff")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return FrontmatterResult({}, normalized, ("frontmatter_missing",))

    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), -1)
    if closing < 0:
        return FrontmatterResult({}, normalized, ("frontmatter_unclosed",))

    properties: dict[str, Any] = {}
    errors: list[str] = []
    active_list_key = ""
    for line_number, raw in enumerate(lines[1:closing], start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            stripped = raw.strip()
            if active_list_key and stripped.startswith("-"):
                value = _parse_scalar(stripped[1:].strip())
                current = properties.setdefault(active_list_key, [])
                if isinstance(current, list):
                    current.append(value)
                else:
                    errors.append(f"frontmatter_list_conflict:{line_number}")
                continue
            errors.append(f"frontmatter_nested_mapping_unsupported:{line_number}")
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$", raw)
        if not match:
            errors.append(f"frontmatter_invalid_line:{line_number}")
            active_list_key = ""
            continue
        key = match.group(1)
        value_text = match.group(2) or ""
        if key in properties:
            errors.append(f"frontmatter_duplicate_key:{key}")
        if value_text.strip() == "":
            properties[key] = [] if key in LIST_PROPERTIES else ""
            active_list_key = key
        else:
            properties[key] = _parse_scalar(value_text)
            active_list_key = ""

    body = "\n".join(lines[closing + 1 :])
    if normalized.endswith("\n"):
        body += "\n"
    return FrontmatterResult(properties, body, tuple(errors))


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if (
        not text
        or text != text.strip()
        or re.search(r"[:#\[\]{},&*!|>'\"%@`]", text)
        or text.lower() in {"true", "false", "null", "~"}
        or text.startswith(("-", "?"))
    ):
        return json.dumps(text, ensure_ascii=False)
    return text


def render_frontmatter(properties: Mapping[str, Any]) -> str:
    """Render deterministic Obsidian YAML for the v2 properties contract."""
    validation = validate_frontmatter_properties(properties)
    if validation:
        codes = ", ".join(issue["code"] for issue in validation)
        raise ValueError(f"Invalid DeepPaperNote v2 frontmatter: {codes}")

    ordered_keys = [key for key in REQUIRED_PROPERTIES if key in properties]
    ordered_keys.extend(key for key in OPTIONAL_PROPERTIES if key in properties)
    ordered_keys.extend(
        sorted(
            key
            for key in properties
            if key not in REQUIRED_PROPERTIES and key not in OPTIONAL_PROPERTIES
        )
    )
    lines = ["---"]
    for key in ordered_keys:
        value = properties[key]
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return not value or any(is_empty_value(item) for item in value)
    return False


def has_chinese(value: Any) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value)))


def has_latin(value: Any) -> bool:
    return bool(re.search(r"[A-Za-z]", str(value)))


def is_absolute_local_path(value: str) -> bool:
    return bool(
        re.match(r"(?i)^[A-Z]:[\\/]", value.strip())
        or value.strip().startswith("\\\\")
        or re.match(r"^/(?:Users|home)/", value.strip())
    )


def is_zotero_deleted_library_path(path: PurePosixPath) -> bool:
    """Return whether a Vault-relative path belongs to the ignored archive tree."""
    return (
        len(path.parts) >= 2
        and path.parts[0].casefold() == LOCAL_PDF_LIBRARY_ROOT.casefold()
        and path.parts[1].casefold() == ZOTERO_DELETED_COLLECTION.casefold()
    )


def is_safe_library_pdf_path(value: str) -> bool:
    """Accept only a non-escaping Vault-relative PDF below 文献/<collection>/<paper>/."""
    raw = urllib.parse.unquote(str(value or "")).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    return bool(
        raw
        and not path.is_absolute()
        and len(path.parts) >= 4
        and path.parts[0] == LOCAL_PDF_LIBRARY_ROOT
        and not is_zotero_deleted_library_path(path)
        and path.suffix.casefold() == ".pdf"
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _property_issue(code: str, prop: str, message: str) -> dict[str, str]:
    return {"code": code, "property": prop, "message": message}


def validate_frontmatter_properties(properties: Mapping[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for key in REQUIRED_PROPERTIES:
        if key not in properties:
            issues.append(
                _property_issue(
                    "required_property_missing", key, f"Missing required property: {key}"
                )
            )
        elif is_empty_value(properties[key]):
            issues.append(
                _property_issue(
                    "required_property_empty", key, f"Required property is empty: {key}"
                )
            )

    for key, allowed in PROPERTY_ENUMS.items():
        if key in properties and str(properties[key]) not in allowed:
            issues.append(
                _property_issue(
                    "property_enum_invalid",
                    key,
                    f"{key} must be one of: {', '.join(sorted(allowed))}",
                )
            )

    for key in LIST_PROPERTIES:
        if key in properties and not isinstance(properties[key], list):
            issues.append(
                _property_issue("property_list_required", key, f"{key} must be a YAML list")
            )

    aliases = properties.get("aliases")
    if isinstance(aliases, list):
        if not any(has_chinese(alias) for alias in aliases):
            issues.append(
                _property_issue(
                    "chinese_alias_missing", "aliases", "At least one Chinese alias is required"
                )
            )
        if not any(has_latin(alias) for alias in aliases):
            issues.append(
                _property_issue(
                    "latin_alias_missing", "aliases", "At least one Latin-script alias is required"
                )
            )

    title_zh = properties.get("title_zh")
    if title_zh and not has_chinese(title_zh):
        issues.append(
            _property_issue(
                "title_zh_not_chinese", "title_zh", "title_zh must contain Chinese text"
            )
        )

    year = str(properties.get("year", ""))
    if year and not YEAR_RE.fullmatch(year):
        issues.append(
            _property_issue("year_invalid", "year", "year must be a four-digit publication year")
        )

    topics = properties.get("topics")
    if isinstance(topics, list) and not 2 <= len(topics) <= 6:
        issues.append(
            _property_issue(
                "topics_count_invalid", "topics", "topics must contain 2 to 6 controlled terms"
            )
        )

    tags = properties.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not TAG_RE.fullmatch(str(tag)):
                issues.append(
                    _property_issue(
                        "tag_taxonomy_invalid",
                        "tags",
                        f"Tag must use lowercase papers/<domain> hierarchy: {tag}",
                    )
                )

    allowed_keys = set(REQUIRED_PROPERTIES) | set(OPTIONAL_PROPERTIES) | set(LEGACY_PROPERTIES)
    for key, value in properties.items():
        if key in OPTIONAL_PROPERTIES and is_empty_value(value):
            issues.append(
                _property_issue(
                    "optional_property_empty", key, f"Omit empty optional property: {key}"
                )
            )
        if key not in allowed_keys:
            issues.append(_property_issue("property_unknown", key, f"Unknown v2 property: {key}"))

    for key in ("local_pdf", "supplement_pdfs"):
        value = properties.get(key)
        values = value if isinstance(value, list) else [value] if value else []
        for item in values:
            if is_absolute_local_path(str(item)):
                issues.append(
                    _property_issue(
                        "local_source_absolute", key, f"{key} must be Vault-relative, not absolute"
                    )
                )
            elif not is_safe_library_pdf_path(str(item)):
                issues.append(
                    _property_issue(
                        "local_source_path_invalid",
                        key,
                        f"{key} must be a PDF under 文献/<collection>/<paper>/",
                    )
                )
    return issues


def normalize_lookup_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", urllib.parse.unquote(value or "")).casefold()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"[\s\-_/\\:：.,;，。；'\"‘’“”()（）\[\]{}<>|?*\x00-\x1f]+", "", normalized)
    return normalized


def folder_title_matches(title: str, folder_name: str) -> bool:
    """Allow a canonical title or a Zotero collision suffix."""
    if normalize_lookup_key(title) == normalize_lookup_key(folder_name):
        return True
    collision_free = re.sub(r"\s*\[[A-Za-z0-9]{8}\]\s*$", "", folder_name)
    return normalize_lookup_key(title) == normalize_lookup_key(collision_free)


def _first_h1(body: str) -> str:
    match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def discover_notes(vault_root: Path) -> list[NoteRecord]:
    library = vault_root / PAPER_LIBRARY_PATH
    if not library.exists():
        return []
    deleted_root = library / ZOTERO_DELETED_COLLECTION
    records: list[NoteRecord] = []
    for path in sorted(library.rglob(NOTE_FILENAME), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        try:
            path.relative_to(deleted_root)
        except ValueError:
            pass
        else:
            continue
        text = path.read_text(encoding="utf-8-sig")
        parsed = parse_frontmatter(text)
        records.append(
            NoteRecord(
                path=path,
                relative_path=path.relative_to(vault_root).as_posix(),
                folder_name=path.parent.name,
                properties=parsed.properties,
                body=parsed.body,
                title_heading=_first_h1(parsed.body),
                parse_errors=parsed.errors,
            )
        )
    return records


def build_note_index(records: Iterable[NoteRecord]) -> dict[str, list[NoteRecord]]:
    index: dict[str, list[NoteRecord]] = {}
    for record in records:
        candidates: list[Any] = [
            record.folder_name,
            record.properties.get("title", ""),
            record.properties.get("title_zh", ""),
            record.properties.get("doi", ""),
        ]
        aliases = record.properties.get("aliases", [])
        if isinstance(aliases, list):
            candidates.extend(aliases)
        for candidate in candidates:
            key = normalize_lookup_key(str(candidate))
            if key:
                bucket = index.setdefault(key, [])
                if record not in bucket:
                    bucket.append(record)
    return index


def extract_wikilinks(text: str) -> list[WikiLink]:
    links: list[WikiLink] = []
    for match in WIKILINK_RE.finditer(text):
        raw = match.group(2).strip()
        target = raw.split("|", 1)[0].strip()
        links.append(WikiLink(raw=raw, target=target, embedded=bool(match.group(1))))
    return links


def _markdown_image_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")].strip()
    return raw.split(maxsplit=1)[0].strip()


def paper_local_image_names(note_text: str) -> tuple[set[str], list[str]]:
    """Return strict ``images/<basename>`` embeds and reader-image violations."""
    raw_targets = [
        target.split("|", 1)[0].strip() for target in re.findall(r"!\[\[([^\]]+)\]\]", note_text)
    ]
    raw_targets.extend(
        _markdown_image_target(target) for target in MARKDOWN_IMAGE_RE.findall(note_text)
    )
    names: set[str] = set()
    failures: list[str] = []
    if HTML_IMAGE_RE.search(note_text):
        failures.append("html_image_embed_forbidden")
    if REFERENCE_IMAGE_RE.search(note_text) or SHORTCUT_IMAGE_RE.search(note_text):
        failures.append("reference_image_embed_forbidden")
    for target in raw_targets:
        normalized = target.strip().strip("<>").replace("\\", "/")
        if normalized.startswith("//") or re.match(
            r"^[a-z][a-z0-9+.-]*:", normalized, flags=re.IGNORECASE
        ):
            failures.append(f"external_image_forbidden:{target}")
            continue
        parts = [part for part in normalized.split("/") if part]
        suffix = Path(normalized).suffix.lower()
        looks_local_image = suffix in IMAGE_EXTENSIONS or (
            parts and parts[0].casefold() == "images"
        )
        if not looks_local_image:
            continue
        if (
            len(parts) != 2
            or parts[0] != "images"
            or parts[1] in {".", ".."}
            or suffix not in IMAGE_EXTENSIONS
        ):
            failures.append(f"image_reference_unsafe:{target}")
            continue
        names.add(parts[1])
    return names, failures


def is_local_pdf_library_link(link: WikiLink) -> bool:
    """Return whether a non-embedded link targets the local-only PDF library."""
    if link.embedded:
        return False
    target = re.split(r"[#^]", link.target, maxsplit=1)[0].strip()
    normalized = urllib.parse.unquote(target).replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        bool(normalized)
        and not path.is_absolute()
        and len(path.parts) >= 4
        and path.parts[0] == LOCAL_PDF_LIBRARY_ROOT
        and not is_zotero_deleted_library_path(path)
        and path.suffix.casefold() == ".pdf"
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _path_candidates(target: str, source_path: Path, vault_root: Path) -> list[Path]:
    target = urllib.parse.unquote(target).replace("\\", "/").lstrip("/")
    if not target:
        return []
    raw = Path(target)
    roots = [vault_root, source_path.parent]
    candidates: list[Path] = []
    for root in roots:
        base = root / raw
        candidates.append(base)
        if not raw.suffix:
            candidates.append(Path(str(base) + ".md"))
            candidates.append(base / NOTE_FILENAME)
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate).casefold()
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return unique


def _case_insensitive_existing(path: Path, vault_root: Path) -> Path | None:
    try:
        relative = path.resolve().relative_to(vault_root.resolve())
    except (OSError, ValueError):
        return None
    current = vault_root.resolve()
    for part in relative.parts:
        if not current.is_dir():
            return None
        exact = current / part
        if exact.exists():
            current = exact
            continue
        matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
        if len(matches) != 1:
            return None
        current = matches[0]
    return current if current.exists() else None


def resolve_link_target(
    target: str,
    *,
    source_path: Path,
    vault_root: Path,
    note_index: Mapping[str, list[NoteRecord]],
) -> LinkResolution:
    target = target.strip()
    if not target or target.startswith(("#", "^")):
        return LinkResolution("local_anchor", source_path)
    if re.match(r"^[a-z][a-z0-9+.-]*://", target, flags=re.IGNORECASE):
        return LinkResolution("external")
    file_target = re.split(r"[#^]", target, maxsplit=1)[0].strip()
    for candidate in _path_candidates(file_target, source_path, vault_root):
        existing = _case_insensitive_existing(candidate, vault_root)
        if existing is not None:
            return LinkResolution("resolved", existing)

    lookup_candidates = [file_target, Path(file_target).name]
    if Path(file_target).name in {"笔记", NOTE_FILENAME} and len(Path(file_target).parts) > 1:
        lookup_candidates.append(Path(file_target).parent.name)
    matches: list[NoteRecord] = []
    for lookup in lookup_candidates:
        key = normalize_lookup_key(lookup)
        for record in note_index.get(key, []):
            if record not in matches:
                matches.append(record)
    if len(matches) == 1:
        return LinkResolution("resolved", matches[0].path)
    if len(matches) > 1:
        return LinkResolution(
            "ambiguous", candidates=tuple(record.relative_path for record in matches)
        )
    return LinkResolution("missing")


def note_wikilink(record: NoteRecord, display: str | None = None) -> str:
    target = record.relative_path.removesuffix(".md")
    label = display or str(
        record.properties.get("title_zh") or record.properties.get("title") or record.folder_name
    )
    return f"[[{target}|{label}]]"


def validate_image_file(path: Path) -> str:
    """Return an empty string only when an image is structurally usable."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"unreadable:{exc.__class__.__name__}"
    suffix = path.suffix.lower()
    if not data:
        return "empty"
    if suffix == ".svg":
        try:
            root = ET.fromstring(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ET.ParseError):
            return "invalid_svg_xml"
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            return "invalid_svg_root"
        return ""
    if suffix not in IMAGE_EXTENSIONS:
        return "unsupported_image_extension"

    try:
        pixmap = fitz.Pixmap(str(path))
        if pixmap.width <= 0 or pixmap.height <= 0 or pixmap.n <= 0:
            return "invalid_raster_dimensions"
    except Exception as exc:
        return f"raster_decode_failed:{exc.__class__.__name__}"
    return ""


def _issue(
    issues: list[VaultIssue],
    code: str,
    path: str,
    message: str,
    *,
    severity: str = "error",
    **details: Any,
) -> None:
    issues.append(VaultIssue(code, path, message, severity, details))


def _resolved_relative(path: Path, vault_root: Path) -> str:
    return path.resolve().relative_to(vault_root.resolve()).as_posix()


def _collect_document_links(
    text: str,
    *,
    source_path: Path,
    vault_root: Path,
    note_index: Mapping[str, list[NoteRecord]],
    issues: list[VaultIssue],
    referenced_images: set[str],
    allow_missing_local_pdfs: bool,
) -> set[str]:
    resolved_notes: set[str] = set()
    source_relative = source_path.relative_to(vault_root).as_posix()
    for link in extract_wikilinks(text):
        resolution = resolve_link_target(
            link.target,
            source_path=source_path,
            vault_root=vault_root,
            note_index=note_index,
        )
        if resolution.status == "missing":
            if allow_missing_local_pdfs and is_local_pdf_library_link(link):
                continue
            _issue(
                issues,
                "wikilink_broken",
                source_relative,
                f"Unresolved wikilink: {link.raw}",
                target=link.target,
            )
            continue
        if resolution.status == "ambiguous":
            _issue(
                issues,
                "wikilink_ambiguous",
                source_relative,
                f"Ambiguous wikilink: {link.raw}",
                target=link.target,
                candidates=list(resolution.candidates),
            )
            continue
        if resolution.status != "resolved" or resolution.path is None:
            continue
        relative = _resolved_relative(resolution.path, vault_root)
        if resolution.path.suffix.lower() in IMAGE_EXTENSIONS:
            if not link.embedded:
                _issue(
                    issues,
                    "image_not_embedded",
                    source_relative,
                    f"Image is linked but not embedded: {link.raw}",
                )
            referenced_images.add(relative.casefold())
        elif resolution.path.name == NOTE_FILENAME:
            resolved_notes.add(relative.casefold())

    for match in MARKDOWN_IMAGE_RE.finditer(text):
        raw = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
        if raw.startswith(("http://", "https://", "data:")):
            continue
        resolution = resolve_link_target(
            raw,
            source_path=source_path,
            vault_root=vault_root,
            note_index=note_index,
        )
        if resolution.status != "resolved" or resolution.path is None:
            _issue(
                issues,
                "markdown_embed_broken",
                source_relative,
                f"Unresolved Markdown image: {raw}",
            )
            continue
        referenced_images.add(_resolved_relative(resolution.path, vault_root).casefold())
    return resolved_notes


def _validate_base_file(path: Path, vault_root: Path, issues: list[VaultIssue]) -> None:
    relative = path.relative_to(vault_root).as_posix()
    if not path.exists():
        _issue(issues, "paper_base_missing", relative, f"{BASE_PATH.as_posix()} is required")
        return
    text = path.read_text(encoding="utf-8-sig")
    try:
        definition = parse_base_definition(text)
    except ValueError as error:
        _issue(
            issues,
            "paper_base_parse_error",
            relative,
            f"Invalid Obsidian Base structure: {error}",
        )
        return

    actual_views = set(definition.views)
    for view in BASE_REQUIRED_VIEWS:
        if view not in actual_views:
            _issue(
                issues,
                "paper_base_view_missing",
                relative,
                f"Missing Base view: {view}",
                view=view,
            )
    for view in sorted(actual_views - set(BASE_REQUIRED_VIEWS), key=str.casefold):
        _issue(
            issues,
            "paper_base_view_unexpected",
            relative,
            f"Unexpected Base view: {view}",
            view=view,
        )

    missing_filters = [
        expression
        for expression in BASE_REQUIRED_FILTERS
        if expression not in set(definition.global_filters)
    ]
    if missing_filters:
        _issue(
            issues,
            "paper_base_filter_invalid",
            relative,
            "Base must select only \u6587\u732e/**/\u7b14\u8bb0.md",
            missing=missing_filters,
        )


def _paper_directory_images(
    paper_dir: Path,
    vault_root: Path,
    issues: list[VaultIssue],
    *,
    allow_nested_directories: bool = False,
) -> list[Path]:
    """Validate one permanent paper directory and return supported image files."""
    paper_relative = paper_dir.relative_to(vault_root).as_posix()
    image_files: list[Path] = []
    for entry in sorted(paper_dir.iterdir(), key=lambda item: item.name.casefold()):
        if entry.name == NOTE_FILENAME:
            if not entry.is_file():
                _issue(
                    issues,
                    "note_not_file",
                    f"{paper_relative}/{NOTE_FILENAME}",
                    f"{NOTE_FILENAME} must be a regular file",
                )
            continue
        if entry.is_file() and entry.suffix.casefold() == ".pdf":
            continue
        if entry.name != "images":
            if entry.is_dir() and allow_nested_directories:
                continue
            _issue(
                issues,
                "paper_directory_extra_entry",
                paper_relative,
                "Paper directories may contain PDFs, the note, and an optional images/ directory",
                entry=entry.name,
            )
            continue
        if not entry.is_dir():
            _issue(
                issues,
                "images_not_directory",
                f"{paper_relative}/images",
                "Paper-local images must be a directory when present",
            )
            continue
        for image in sorted(entry.iterdir(), key=lambda item: item.name.casefold()):
            relative = image.relative_to(vault_root).as_posix()
            if not image.is_file():
                _issue(
                    issues,
                    "images_extra_entry",
                    relative,
                    "images/ may contain only supported image files",
                )
            elif image.suffix.lower() not in IMAGE_EXTENSIONS:
                _issue(
                    issues,
                    "image_extension_unsupported",
                    relative,
                    "images/ contains an unsupported file type",
                )
            else:
                image_files.append(image)
    return image_files


def _validate_library_structure(
    vault_root: Path,
    issues: list[VaultIssue],
) -> list[Path]:
    """Validate nested Zotero-backed paper directories without requiring notes."""
    legacy_research = vault_root / "Research"
    if legacy_research.exists():
        _issue(
            issues,
            "legacy_research_directory_present",
            "Research",
            "Research/ is obsolete; migrate its notes into the \u6587\u732e/ paper tree",
        )

    library = vault_root / PAPER_LIBRARY_PATH
    library_relative = PAPER_LIBRARY_PATH.as_posix()
    if not library.is_dir():
        _issue(
            issues,
            "paper_library_missing",
            library_relative,
            f"{library_relative}/ is required",
        )
        return []

    image_files: list[Path] = []

    def walk(directory: Path, *, depth: int, is_root: bool = False) -> None:
        entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        relative = directory.relative_to(vault_root).as_posix()
        if is_root:
            for entry in entries:
                entry_relative = entry.relative_to(vault_root).as_posix()
                if entry.is_file() and entry.name in {NAVIGATION_PATH.name, BASE_PATH.name}:
                    continue
                if entry.is_dir():
                    if entry.name == ZOTERO_DELETED_COLLECTION:
                        continue
                    if entry.name.startswith("."):
                        _issue(
                            issues,
                            "library_temporary_directory",
                            entry_relative,
                            "Temporary directories must not remain in \u6587\u732e/",
                        )
                    else:
                        walk(entry, depth=1)
                    continue
                _issue(
                    issues,
                    "library_root_extra_entry",
                    entry_relative,
                    (
                        "\u6587\u732e/ root may contain only navigation, Base files, "
                        "and collection directories"
                    ),
                )
            return

        has_note = any(entry.name == NOTE_FILENAME for entry in entries)
        has_pdf = any(entry.is_file() and entry.suffix.casefold() == ".pdf" for entry in entries)
        has_images = any(entry.name == "images" for entry in entries)
        if has_note or has_pdf or has_images:
            if depth < 2:
                _issue(
                    issues,
                    "paper_directory_shallow",
                    relative,
                    "Paper directories must be below 文献/<分类>/<论文>/",
                )
                if has_images and not (directory / NOTE_FILENAME).is_file():
                    _issue(
                        issues,
                        "paper_directory_note_missing",
                        relative,
                        f"A paper directory with images must contain {NOTE_FILENAME}",
                    )
                image_files.extend(
                    _paper_directory_images(
                        directory,
                        vault_root,
                        issues,
                        allow_nested_directories=True,
                    )
                )
                for entry in entries:
                    entry_relative = entry.relative_to(vault_root).as_posix()
                    if not entry.is_dir() or entry.name == "images":
                        continue
                    if entry.name.startswith("."):
                        _issue(
                            issues,
                            "library_temporary_directory",
                            entry_relative,
                            "Temporary directories must not remain in 文献/",
                        )
                    else:
                        walk(entry, depth=depth + 1)
                return
            if has_images and not (directory / NOTE_FILENAME).is_file():
                _issue(
                    issues,
                    "paper_directory_note_missing",
                    relative,
                    f"A paper directory with images must contain {NOTE_FILENAME}",
                )
            image_files.extend(_paper_directory_images(directory, vault_root, issues))
            return

        for entry in entries:
            entry_relative = entry.relative_to(vault_root).as_posix()
            if entry.is_dir():
                if entry.name.startswith("."):
                    _issue(
                        issues,
                        "library_temporary_directory",
                        entry_relative,
                        "Temporary directories must not remain in \u6587\u732e/",
                    )
                else:
                    walk(entry, depth=depth + 1)
                continue
            _issue(
                issues,
                "collection_directory_extra_entry",
                entry_relative,
                "Collection directories may contain only nested collections or paper directories",
            )

    walk(library, depth=0, is_root=True)
    return image_files


def lint_vault(vault_root: Path, *, allow_missing_local_pdfs: bool = False) -> dict[str, Any]:
    vault_root = vault_root.expanduser().resolve()
    records = discover_notes(vault_root)
    note_index = build_note_index(records)
    issues: list[VaultIssue] = []
    referenced_images: set[str] = set()
    note_paths = {record.relative_path.casefold() for record in records}
    all_images = _validate_library_structure(vault_root, issues)

    for record in records:
        for parse_error in record.parse_errors:
            _issue(issues, parse_error.split(":", 1)[0], record.relative_path, parse_error)
        for frontmatter_issue in validate_frontmatter_properties(record.properties):
            _issue(
                issues,
                frontmatter_issue["code"],
                record.relative_path,
                frontmatter_issue["message"],
                property=frontmatter_issue["property"],
            )
        property_title = str(record.properties.get("title", ""))
        if property_title and not folder_title_matches(property_title, record.folder_name):
            _issue(
                issues,
                "title_folder_mismatch",
                record.relative_path,
                (
                    "Frontmatter title must match the canonical paper folder "
                    "(with an optional Zotero item-key suffix)"
                ),
                title=property_title,
                folder=record.folder_name,
            )
        if not record.title_heading:
            _issue(
                issues,
                "title_heading_missing",
                record.relative_path,
                "The note must contain one H1 title",
            )
        complete_text = render_unvalidated_frontmatter(record.properties) + record.body
        absolute_match = ABSOLUTE_PATH_RE.search(complete_text)
        if absolute_match:
            _issue(
                issues,
                "absolute_path_present",
                record.relative_path,
                "Permanent notes must not contain machine-absolute paths",
                match=absolute_match.group(0),
            )
        for pattern in RUNTIME_STATUS_PATTERNS:
            match = pattern.search(complete_text)
            if match:
                _issue(
                    issues,
                    "runtime_status_present",
                    record.relative_path,
                    "Runtime integration status must stay in run artifacts, not permanent notes",
                    match=match.group(0),
                )
                break
        lowered = complete_text.replace("\\", "/").casefold()
        for path_part in TEMP_PATH_PARTS:
            if path_part in lowered:
                _issue(
                    issues,
                    "temporary_path_present",
                    record.relative_path,
                    f"Permanent note references temporary output: {path_part}",
                    match=path_part,
                )

        _, image_reference_failures = paper_local_image_names(record.body)
        for failure in image_reference_failures:
            code = failure.split(":", 1)[0]
            _issue(
                issues,
                code,
                record.relative_path,
                "Paper notes may embed only reviewed paper-local images",
                detail=failure,
            )

        _collect_document_links(
            record.body,
            source_path=record.path,
            vault_root=vault_root,
            note_index=note_index,
            issues=issues,
            referenced_images=referenced_images,
            allow_missing_local_pdfs=allow_missing_local_pdfs,
        )

    # Collisions are warnings until an actual link resolves ambiguously.
    for key, matches in note_index.items():
        if len(matches) > 1:
            _issue(
                issues,
                "link_index_collision",
                PAPER_LIBRARY_PATH.as_posix(),
                "Multiple notes share a title, alias, or DOI lookup key",
                severity="warning",
                key=key,
                candidates=[record.relative_path for record in matches],
            )

    navigation_path = vault_root / NAVIGATION_PATH
    navigation_note_paths: set[str] = set()
    if not navigation_path.exists():
        _issue(
            issues,
            "paper_navigation_missing",
            NAVIGATION_PATH.as_posix(),
            f"{NAVIGATION_PATH.as_posix()} is required",
        )
    else:
        navigation_text = navigation_path.read_text(encoding="utf-8-sig")
        navigation_note_paths = _collect_document_links(
            navigation_text,
            source_path=navigation_path,
            vault_root=vault_root,
            note_index=note_index,
            issues=issues,
            referenced_images=referenced_images,
            allow_missing_local_pdfs=allow_missing_local_pdfs,
        )
        missing_from_navigation = sorted(note_paths - navigation_note_paths)
        for missing in missing_from_navigation:
            _issue(
                issues,
                "note_missing_from_navigation",
                NAVIGATION_PATH.as_posix(),
                "Every paper note must be reachable from the navigation note",
                note=missing,
            )

    _validate_base_file(vault_root / BASE_PATH, vault_root, issues)

    all_images.sort(key=lambda item: item.as_posix().casefold())
    for image in all_images:
        relative = image.relative_to(vault_root).as_posix()
        corruption = validate_image_file(image)
        if corruption:
            _issue(
                issues,
                "image_corrupt",
                relative,
                f"Image failed container validation: {corruption}",
            )
        if relative.casefold() not in referenced_images:
            _issue(issues, "image_orphan", relative, "Image is not referenced by any paper note")

    error_count = sum(issue.severity == "error" for issue in issues)
    warning_count = sum(issue.severity == "warning" for issue in issues)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if error_count == 0 else "fail",
        "vault": str(vault_root),
        "summary": {
            "notes": len(records),
            "images": len(all_images),
            "errors": error_count,
            "warnings": warning_count,
            "navigation_coverage": len(navigation_note_paths & note_paths),
        },
        "notes": [
            {
                "path": record.relative_path,
                "sha256": sha256_file(record.path),
                "title": record.properties.get("title", ""),
                "title_zh": record.properties.get("title_zh", ""),
            }
            for record in records
        ],
        "issues": [issue.as_dict() for issue in issues],
    }


def render_unvalidated_frontmatter(properties: Mapping[str, Any]) -> str:
    """Render properties for diagnostics without applying the v2 gate."""
    lines: list[str] = []
    for key, value in properties.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"

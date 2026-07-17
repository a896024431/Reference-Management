# Vault v2

Use this reference for permanent Obsidian properties, links, navigation and Vault-wide publication checks.

## Permanent note properties

Every `Research/<canonical title>/笔记.md` uses the following required properties:

- `type: paper`
- `title` and `title_zh`
- `authors`, `year`, and `venue`
- `domain` and 2–6 controlled `topics`
- `paper_type`
- `evidence_level`
- `note_status`
- `figure_status`
- `aliases` with at least one Latin-script and one Chinese alias
- lowercase hierarchical `tags` beginning with `papers/`

Allowed `paper_type` values:

- `experimental_physics`
- `theoretical_physics`
- `materials_fabrication`
- `ai_method`
- `benchmark`
- `clinical`
- `humanities`
- `survey`
- `generic`

Allowed state values:

- `evidence_level`: `abstract_only`, `full_text`, `full_text_supplement`
- `note_status`: `draft`, `reviewed`, `polished`, `degraded`
- `figure_status`: `complete`, `partial`, `placeholder_only`, `none_needed`

Optional properties are emitted only when non-empty:

- `date`, `doi`, `arxiv`, `source_url`
- `local_pdf`, `supplement_pdfs`
- `methods`, `materials`
- `code_url`, `project_url`
- `zotero_key`, `zotero_uri`

Local source paths must be Vault-relative. Never persist a drive-qualified path or a runtime integration message.

## Reader-Facing Figure Boundary

`笔记.md` is for reading, not for pipeline diagnostics. An inserted figure may use a direct Obsidian embed and a concise natural caption. All decision states and engineering metadata — including visible placeholders, `[!figure]` callouts, `建议位置`, `放置原因`, `当前状态`, candidate IDs, crop coordinates, hashes, rejection reasons, and visual-QA status — belong only in `.local/deeppapernote/runs/<run_id>/` artifacts and are forbidden in a permanent note.

Use `scripts/vault.py::render_frontmatter` instead of ad hoc YAML formatting. The parser intentionally accepts only top-level scalars and lists so malformed or unexpectedly nested properties fail closed.

## Links

Build the note index from canonical folder title, `title`, `title_zh`, aliases and DOI. Resolve an existing note before emitting a wikilink. A DOI/title/alias collision is ambiguous and must not be guessed.

Use confirmed targets in this form:

```md
[[Research/Canonical Paper Title/笔记|可读标题]]
```

When no target resolves uniquely, retain plain citation text. Do not invent a path.

## Navigation and Bases

- `Research/论文库.base` is the property-driven database entry point.
- `Research/论文导航.md` embeds that Base and contains real links to every paper note.
- Every paper must be reachable from the navigation note, even if it has no paper-to-paper incoming link yet.

The Base exposes four views:

- `全部论文`
- `待补图`
- `待复核`
- `按主题`

Do not add Dataview as a hidden dependency.

## Excluded local output

Configure the local Obsidian setting `userIgnoreFilters` for:

- `.local/`
- `tmp/`
- `DeepPaperNote_output/`

The `.obsidian/` directory remains machine-local and must not be committed.

## Publication check

Run:

```powershell
C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe scripts/lint_vault.py --vault <vault-root>
```

The validator checks:

- v2 properties and enumerations
- bilingual aliases and controlled tag syntax
- machine-absolute and temporary paths
- permanent runtime availability messages
- broken or ambiguous wikilinks
- broken Markdown and Obsidian embeds
- missing or corrupt image containers
- orphan images under paper-local `images/`
- Base views and complete navigation coverage
- reader-visible figure-planning/QA metadata and hidden figure comments

`--no-fail` is allowed only for migration audits. It preserves `status: fail` in the JSON report while exiting zero so all legacy problems can be collected. Never use it to publish a note as complete.

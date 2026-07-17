# Obsidian Format

## Heading Rules

- Use `#` for the note title only.
- Use `##` for major sections.
- Use `###` only when a section genuinely needs internal structure.
- Do not flatten everything into bullet points.
- For method, system, benchmark, or clinical empirical papers, prefer meaningful `###` subheadings in technical sections instead of one long undifferentiated block.
- For method, framework, or system papers, default to `### 机制流程` inside `方法主线` and write it as a numbered 3 to 4 step flow.

## File Naming

Default file name:
- `笔记.md`
- default note layout is folder-per-paper:
  - `<paper_title>/笔记.md`
  - `<paper_title>/images/...`
- do not add domain/category directory layers by default
- do not save new papers directly into the bare `Research` root
- always create the paper-local `images/` directory during final save, even if no real image is inserted
- the paper-local `images/` directory is part of the required note layout, not an optional optimization
- if the target is an Obsidian vault but the current environment cannot create that directory yet, request permission escalation rather than omitting it

If the user already has a vault convention, preserve it.

## Markdown Style

- Prefer short paragraphs over long bullet lists.
- Use bullets for metadata and sharply list-shaped content.
- Keep code or metric identifiers in backticks.
- Preserve stable internal links where useful.
- Use normal LaTeX delimiters for math:
  - inline math: `$...$`
  - display math:
    `$$`
    `...`
    `$$`
- Do not wrap formulas in backticks or fenced code blocks unless you are literally showing source code.

## Core Info Block

`## 核心信息` is a fixed metadata zone.

Formatting and scope rules:
- use the stable template-style metadata bullets only
- keep each entry in `- 字段名: 值` form
- do not add interpretation, commentary, judgment, or takeaway lines inside `核心信息`
- do not use the last metadata bullet as a place to append extra analysis
- if a field is missing, leave it blank or mark it as unavailable rather than replacing the field with prose
- move explanatory content to `一句话总结`、`深度分析`、`我的笔记` or another true analysis section

## YAML Frontmatter

Every note must start with an Obsidian properties block **above** the `#` title heading.

Required fields:
- `tags`: use `papers/<domain>` hierarchy, e.g. `papers/NLP`, `papers/CV`, `papers/multimodal`
- `aliases`: English short name or common abbreviation for wikilink resolution
- `date`: ISO publication date; use `YYYY` if only the year is known
- `doi`: DOI string without the `https://doi.org/` prefix; omit the field entirely if unavailable

Example:

```yaml
---
tags:
  - papers/NLP
aliases:
  - "Paper Short Name"
date: 2024-05-01
doi: 10.18653/v1/2024.acl-long.1
---
```

Rules:
- Do not invent placeholder values for missing fields; omit them instead.
- The `tags` field must always be present with at least one `papers/<domain>` tag.
- `aliases` should be the paper's short name or acronym (e.g. "GPT-4", "LoRA"), not a paraphrase.

## Figures in Reader-Facing Notes

Use an image block only for an accepted, materialized figure or table. The permanent note must contain only the image and normal explanatory prose:

```md
![[Research/paper_title/images/fig-doc-example-p0003-fig-2.png|420]]
*Fig. 2｜数据生成流程。它说明了为何这个处理步骤决定了后续结果的可比性。*
```

Formatting rules:

- Preserve the original paper numbering, for example `Fig. 3`, `Table 2`, `Fig. S2`, or `Extended Data Fig. 1`.
- Keep the caption short, natural, and useful for reading the surrounding section.
- Do not use `[!figure]`, visible placeholders, `建议位置`, `放置原因`, `当前状态`, internal HTML comments, candidate IDs, crop details, hashes, or QA language.
- If an important visual cannot be inserted reliably, do not expose a placeholder. Store the decision and reason only in the run artifacts and keep the scientific explanation in prose.

The structured `[FIGURE_PLACEHOLDER] ... [/FIGURE_PLACEHOLDER]` block is legacy/internal only and is forbidden in permanent user-facing notes.

## Default Section Order

1. `核心信息`
2. `原文摘要翻译`
3. `创新点`
4. `一句话总结`
5. `研究问题`
6. `数据与任务定义`
7. `方法主线`
8. `关键结果`
9. `深度分析`
10. `局限`
11. `我的笔记`
12. `引用`

When abstract metadata exists, `原文摘要翻译` should be a single Chinese translation block for the original abstract rather than a bilingual subsection pair.

This order is the stable backbone, not a full outline.
When the paper is complex, add `###` subsections such as:
- `### 数据来源`
- `### 任务定义`
- `### 机制流程`
- `### 为什么结果成立`
- `### 哪些地方容易被误读`

## 引用 Section Format

Entries in `## 引用` should link to existing notes in the vault where possible.
Follow this priority order for each reference:

1. **Vault lookup first**: check whether the cited paper already has a note in the vault.
   - Match by paper-title folder name under `Research/`.
   - Match by the `aliases` field in the note's YAML frontmatter.
2. **If a match is found**: write a wikilink that separates the target from the display text:
   ```
   - [[Research/Paper Title/笔记|Human Readable Title]]
   ```
3. **If no match is found**: do not invent a wikilink target. Write the reference as plain text instead:
   ```
   - Vaswani et al. (2017). Attention Is All You Need.
   ```

Rules:
- Use the confirmed paper-title folder path when linking to an existing note.
- Do not derive an underscore slug from a title for this vault layout.
- List only papers cited or directly relevant to this note.
- Do not add extra DOIs or author metadata when using wikilink format; the display text is enough.

---
name: zotero-analytical-writer
description: 接收 Zotero 原始语料并生成中文 Obsidian 论文精读笔记；适用于套用论文精读模板、提炼 frontmatter、过滤学术噪音、处理公式风险、写入 note 目录并刷新静态索引。
---

# Zotero Analytical Writer

## Workflow

1. Read the raw JSON or `Raw_Data_Buffer` from `$zotero-data-fetcher`.
2. Load `templates/论文精读模板.md`.
3. Create or update `note/<collection>/<safe-title>.md`.
4. Fill frontmatter with concise Chinese fields.
5. Write analysis sections in Chinese, but keep direct quotes in the original language.
6. Refresh indexes with:

```powershell
python .\scripts\vault\refresh_indexes.py --vault-root .
```

## Frontmatter Rules

Required fields:

- `title`
- `author`
- `year`
- `source`
- `zotero_key`
- `collection`
- `doi`
- `pdf_link`
- `theme`
- `study_area`
- `data_source`
- `methodology`
- `core_variable`
- `key_finding`
- `relevance`

For analytical fields, use one concise Chinese sentence. Do not copy the abstract mechanically.

Reject and rewrite fields when they contain:

- author affiliations
- postal codes
- email addresses
- funding numbers
- journal submission instructions
- raw labels such as `Abstract:` or `摘要：`

## Formula Rules

- Output formulas only when the source text is complete and interpretable.
- Treat isolated fragments such as `\sum`, `ic x`, or random symbol runs as OCR/cache noise.
- If a formula is invalid, delete the formula explanation block instead of inventing meanings.
- If a screenshot or OCR result is not provided, use a short note that the formula requires manual verification.

## Evidence Rules

- Each major finding should have a direct supporting quote or page reference when available.
- Prefer Zotero annotations; use full-text cache as secondary evidence.
- Use Zotero links when possible:
  - item link: `zotero://select/library/items/<ITEMKEY>`
  - PDF page link: `zotero://open-pdf/library/items/<ATTACHMENTKEY>?page=<PAGE>`

## Final Checks

- The note has valid frontmatter and no unreplaced `{{placeholder}}`.
- Required analytical fields are present and not generic filler.
- Markdown has no unclosed `$` math delimiters.
- The note contains no committed local PDF path unless the user explicitly wants it.
- Indexes have been refreshed after creating a new note.

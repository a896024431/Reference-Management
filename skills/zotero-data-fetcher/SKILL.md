---
name: zotero-data-fetcher
description: 根据 Zotero Item Key 或标题，从本机 Zotero 数据目录提取论文元数据、作者、DOI、附件、批注、笔记和全文缓存；适用于为 Obsidian 精读笔记准备原始语料，且严禁翻译、总结或改写原文。
---

# Zotero Data Fetcher

## Workflow

1. Locate Zotero data.
   - Prefer `--zotero-data-dir`.
   - Otherwise read `.local/config.toml`.
   - Never rely on hard-coded paths.
2. Copy `zotero.sqlite` to a temporary directory before querying.
3. Extract the item by `Item Key` first; use title search only as a fallback.
4. Build a `Raw_Data_Buffer` with:
   - bibliographic metadata
   - creators
   - collection names
   - attachments and Zotero links
   - Zotero annotations and notes
   - `.zotero-ft-cache` text from attachment storage folders
5. Return raw source language only.

## Commands

```powershell
python .\scripts\zotero\extract_item_json.py --item-key ABCD1234 --zotero-data-dir "D:\Zotero"
```

```powershell
python .\scripts\zotero\extract_item_json.py --title "paper title fragment" --zotero-data-dir "D:\Zotero" --output .local\raw\item.json
```

## Output Contract

The script emits JSON with these top-level keys:

- `item`
- `metadata`
- `creators`
- `collections`
- `attachments`
- `annotations`
- `notes`
- `fulltext`
- `raw_data_buffer`

## Rules

- Do not translate or summarize.
- Do not invent missing abstracts, page numbers, formulas, or attachment paths.
- Prefer annotations over full-text cache when choosing evidence for the writer.
- Use local PDF paths only for verification; do not commit PDFs or caches.

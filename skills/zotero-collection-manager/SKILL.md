---
name: zotero-collection-manager
description: 批量处理 Zotero 指定 collection 下的论文，适用于从 Zotero 导入 Obsidian 精读笔记、断点续跑、跳过已完成条目、刷新 Vault 索引和维护处理日志的任务。
---

# Zotero Collection Manager

## Workflow

1. Resolve the target collection name and vault root.
   - Default vault root: repository root.
   - Default note directory: `note/<collection>/`.
   - Use `.local/config.toml` when present; otherwise accept command-line paths from the user.
2. Read `note/<collection>/_ProcessLog_进度记录.md`.
   - Treat `✅ 成功` and `⚠️ 跳过` as completed.
   - Treat `❌ 失败` and missing rows as pending.
3. Query Zotero through `scripts/zotero/process_collection.py`.
   - Use a copied SQLite database, never the live `zotero.sqlite` directly.
   - Process items serially.
   - Generate raw buffers under `.local/raw/<collection>/`; these are intentionally ignored by Git.
4. For each pending item, call the downstream workflow:
   - `$zotero-data-fetcher` prepares metadata, annotations, attachments, and full-text cache.
   - `$zotero-analytical-writer` writes or updates the Obsidian note.
5. After a note is successfully written, append a process-log row immediately:

```text
- [x] 2026-05-19 14:00 | ✅ 成功 | ABCD1234 | Paper title
```

6. Refresh the static Vault indexes after any new or changed note:

```powershell
python .\scripts\vault\refresh_indexes.py --vault-root .
```

## Commands

Preview pending items:

```powershell
python .\scripts\zotero\process_collection.py --collection "分类名" --zotero-data-dir "D:\Zotero" --dry-run
```

Extract raw buffers for pending items:

```powershell
python .\scripts\zotero\process_collection.py --collection "分类名" --zotero-data-dir "D:\Zotero"
```

## Rules

- Do not mark an item as `✅ 成功` until a Markdown note exists in `note/<collection>/`.
- Do not batch-write success rows at the end; update the process log after each item.
- Do not commit `.local/raw/`, Zotero databases, PDFs, attachments, or full-text caches.
- If a Zotero item has no usable attachment, cache, annotation, or metadata, write `❌ 失败（原因）` and continue with the next item.

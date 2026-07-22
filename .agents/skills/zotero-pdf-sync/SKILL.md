---
name: zotero-pdf-sync
description: Manually mirror PDF attachments from the local Zotero collection 我的文库/ZJU/课题组 into this Obsidian vault's 文献/ tree. Use when the user asks to synchronize the full library, a collection, or one Zotero item before working with its local PDFs; do not use it while creating or reviewing a DeepPaperNote.
---

# Zotero PDF Sync

Use this skill only for a user-requested, manual refresh. It reads Zotero's loopback-only Local API; never read or write `zotero.sqlite`, use a cloud API key, or start a watcher.

This skill ends at the PDF directory tree. Do not open, lint, review, rewrite, or publish existing `笔记.md`; a whole-paper directory move may carry it and its local images unchanged. Do not rebuild navigation or start DeepPaperNote as part of a sync.

## Run

1. Ensure Zotero is running and **Settings → Advanced → Allow other applications on this computer to communicate with Zotero** is enabled.
2. From the Vault, use the required environment:

   ```powershell
   conda run --no-capture-output -n deeppapernote python .agents/skills/zotero-pdf-sync/scripts/sync_zotero_pdfs.py --vault-root <Vault path>
   ```

   This refreshes the complete `ZJU/课题组` tree. To limit the refresh, add exactly one of:

   ```text
   --collection <path relative to ZJU/课题组>
   --item-key <parent or standalone Zotero item key>
   ```

   Use `--dry-run` before an uncertain refresh. It performs no Vault write.

## Result and safeguards

- Mirror every non-trash PDF attachment, including main text and SI, to `文献/<分类>/<论文题名>/`; ignore snapshots, notes, EPUBs, and other non-PDF attachments.
- Mirror items directly under the `课题组` root to `文献/未分类/<论文题名>/` so every paper still has a category directory. A standalone PDF uses its attachment key as the stable item identity.
- Parent and attachment keys live only in the local sync index: they identify a directory and attachment across title, category, and filename changes, but do not clutter visible folder or PDF names.
- If two current Zotero items resolve to the same category/title directory, or two attachments of one item resolve to the same filename, skip the conflicting item and report it in the summary. Do not merge directories or invent suffixes.
- A parent item may belong to exactly one collection under `ZJU/课题组`. If Zotero places it in multiple collections, stop before writing and ask the user to choose one.
- When a title or classification changes, move the entire paper directory, including PDF/SI, `笔记.md`, and `images/`. Do not inspect or rewrite the note while moving it.
- Reconcile every active paper directory with Zotero: add new PDFs, replace changed PDFs, rename a same-key PDF when its Zotero filename changes, and remove PDFs no longer present in Zotero. This also applies beside an existing note; `笔记.md` and `images/` are left alone.
- Store only the current active-item index and JSON reports in `.local/zotero-pdf-sync/`. A complete root refresh moves a parent item no longer in the configured Zotero scope to `文献/Zotero已删除/<原分类路径>/`; it is removed from the index and is never restored or managed again. A scoped `--collection` or `--item-key` refresh never archives unseen items.
- `文献/Zotero已删除/` is a reserved local archive root and cannot be used as a Zotero 一级分类. Archive collisions receive an `archived-N` suffix rather than overwriting files.
- Do not use a sync as a reason to inspect, lint, review, or regenerate any completed note.

After a successful mirror, use the local PDFs in `文献/` for DeepPaperNote. Do not query Zotero while drafting or reviewing a note.

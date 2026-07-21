---
name: zotero-pdf-sync
description: Manually mirror PDF attachments from the local Zotero collection 我的文库/ZJU/课题组 into this Obsidian vault's 文献/ tree. Use when the user asks to synchronize the full library, a collection, or one Zotero item before working with its local PDFs; do not use it while creating or reviewing a DeepPaperNote.
---

# Zotero PDF Sync

Use this skill only for a user-requested, manual refresh. It reads Zotero's loopback-only Local API; never read or write `zotero.sqlite`, use a cloud API key, or start a watcher.

This skill ends at the PDF directory tree. Do not open, lint, review, rewrite, relocate, or publish existing `笔记.md`; do not rebuild navigation or start DeepPaperNote as part of a sync.

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
- Mirror items directly under the `课题组` root to `文献/未分类/<论文题名>/` so every paper still has a category directory.
- Preserve attachment filenames. Resolve same-folder name collisions by appending the attachment key; resolve same-title paper folders in one category by appending the item key.
- Store only the index, source hashes, and JSON reports in `.local/zotero-pdf-sync/`. Never delete local PDFs because Zotero no longer has an attachment.
- Move an unnoted directory when Zotero's classification or title changes. If it contains `笔记.md`, report the proposed move and keep the directory and its links unchanged.
- Treat a changed PDF next to `笔记.md` as protected and report it instead of overwriting it. Report stale attachments and filesystem conflicts for manual resolution.
- Do not use a sync as a reason to inspect, lint, review, or regenerate any completed note.

After a successful mirror, use the local PDFs in `文献/` for DeepPaperNote. Do not query Zotero while drafting or reviewing a note.

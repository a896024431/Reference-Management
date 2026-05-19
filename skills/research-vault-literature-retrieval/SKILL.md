---
name: research-vault-literature-retrieval
description: 当前研究 Vault 的默认检索技能；适用于用户询问概念、论文、方法、变量、研究区、已有证据、文献比较或片段式追问时，先读索引、再检索 note 目录，并且只基于已有 Obsidian 笔记回答。
---

# Research Vault Literature Retrieval

## Scope

Treat the repository root as the Vault root. Work primarily in:

- `文献索引.md`
- `研究主题索引.md`
- `研究方法索引.md`
- `字段补全检查.md`
- `note/`

## Retrieval Workflow

1. Read index pages first, in this order:
   - `文献索引.md`
   - `研究主题索引.md`
   - `研究方法索引.md`
   - `字段补全检查.md`
2. Use the indexes to identify candidate titles, topics, methods, variables, collections, and missing fields.
3. Search notes with `rg`:

```powershell
rg -n --glob '*.md' "关键词1|keyword2|method|variable" .\note
```

4. Open the most relevant 1-5 notes before answering.
5. Answer only from Vault evidence.

## Default Answer Shape

Use this structure unless the user asks for another format:

1. `结论`
2. `支持文献`
3. `差异/争议`
4. `对我研究的启发`

## Rules

- Do not use external memory as Vault evidence.
- Do not claim a universal definition when the Vault only contains limited notes.
- If evidence is insufficient, write `Vault 中未找到足够依据`.
- Default to read-only; modify notes or indexes only when the user explicitly asks.
- When notes change, refresh indexes with `scripts/vault/refresh_indexes.py`.

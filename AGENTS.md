# Codex Research Vault Agent Guide

本仓库是一个可通过 GitHub 私有仓库同步的 Codex + Obsidian + Zotero 论文库。默认把仓库根目录视为 Obsidian Vault 根目录，`note/` 存放论文精读笔记，根目录四个索引页用于检索。

## 默认工作方式

1. 优先把用户关于文献、概念、方法、变量、研究区和论文比较的问题当作 Vault 检索任务。
2. 回答前先读取根目录索引页，顺序固定为：
   - `文献索引.md`
   - `研究主题索引.md`
   - `研究方法索引.md`
   - `字段补全检查.md`
3. 再用 `rg -n --glob '*.md'` 检索 `note/`，同时搜索中文关键词、英文关键词、方法名、变量名、地区名和论文标题别名。
4. 回答必须基于 Vault 中真实存在的笔记内容。依据不足时写明：`Vault 中未找到足够依据`。
5. 默认只读。只有用户明确要求导入、刷新索引、编辑笔记或同步时，才修改文件。

## Zotero 导入工作流

按顺序使用本仓库 skills：

1. `$zotero-collection-manager`：读取 Zotero collection，检查 `note/<collection>/_ProcessLog_进度记录.md`，只处理未完成条目。
2. `$zotero-data-fetcher`：从本机 Zotero 数据目录提取单篇论文 metadata、批注、附件和全文缓存，保持原始语言，不翻译不总结。
3. `$zotero-analytical-writer`：套用 `templates/论文精读模板.md` 生成中文 Obsidian 精读笔记，并在新增笔记后刷新四个索引页。

常用脚本：

```powershell
.\scripts\setup.ps1
.\scripts\verify.ps1
python .\scripts\zotero\extract_item_json.py --item-key ABCD1234 --zotero-data-dir "D:\Zotero"
python .\scripts\zotero\process_collection.py --collection "分类名" --zotero-data-dir "D:\Zotero"
python .\scripts\vault\refresh_indexes.py --vault-root .
```

## GitHub 同步边界

只同步 Markdown 笔记、索引、skills、模板、脚本、`AGENTS.md`、`.gitignore`、`.gitattributes`。不要提交 Zotero 数据库、PDF、附件、全文缓存、本机路径配置、密钥、Obsidian 工作区状态和 `.local/`。

两台电脑同步时固定流程：

```powershell
git pull
python .\scripts\vault\refresh_indexes.py --vault-root .
git status --short
git add AGENTS.md .gitignore .gitattributes *.md note skills templates scripts
git commit -m "Update research vault"
git push
```

默认不要在两台电脑上同时批量导入同一个 Zotero collection。若出现冲突，优先保留较新的 Markdown 笔记内容，再重新运行索引刷新脚本。

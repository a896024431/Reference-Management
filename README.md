# Reference Management

一个面向中文研究写作的 Codex + Obsidian + Zotero 联动 Vault。目标是把 Zotero 中的论文、批注和全文缓存转化为可检索、可同步、可由 Codex 继续分析的 Obsidian Markdown 精读笔记。

本仓库支持两台安装 Codex 的电脑通过 GitHub 私有仓库同步研究内容。同步范围严格限制为 Markdown 笔记、索引、skills、模板、脚本和仓库说明；Zotero 数据库、PDF、附件、全文缓存、本机配置和密钥不进入 Git。

## 系统目标

- 从 Zotero collection 批量读取论文条目。
- 提取单篇论文的 metadata、作者、DOI、collection、附件、批注、Zotero note 和 `.zotero-ft-cache` 全文缓存。
- 基于原始语料生成中文 Obsidian 精读笔记。
- 自动维护静态 Markdown 索引，让 Codex 和 Obsidian 都可以直接检索。
- 通过 GitHub private repository 在两台电脑之间同步 Vault 内容。

## 当前自动化边界

脚本层负责稳定、可重复、低风险的自动化：

- 只读复制 Zotero SQLite 后查询，避免锁定或破坏 Zotero 数据库。
- 生成单篇论文 JSON raw buffer。
- 批量枚举 collection 中未处理条目。
- 刷新四个 Markdown 静态索引。
- 验证核心工作流和 Git 忽略边界。

Codex skill 层负责需要判断和写作的部分：

- 将 raw buffer 转换成中文精读笔记。
- 判断研究主题、方法、变量、研究区、关键发现和相关性。
- 过滤作者单位、基金号、邮箱、邮编、OCR 噪音和无效公式。
- 基于 Vault 笔记回答研究问题。

也就是说，`process_collection.py` 会准备原始语料，但不会直接替代 Codex 写中文精读笔记。

## 目录结构

```text
.
├── AGENTS.md
├── README.md
├── .gitignore
├── .gitattributes
├── skills/
│   ├── zotero-collection-manager/
│   ├── zotero-data-fetcher/
│   ├── zotero-analytical-writer/
│   └── research-vault-literature-retrieval/
├── templates/
│   └── 论文精读模板.md
├── scripts/
│   ├── setup.ps1
│   ├── verify.ps1
│   ├── zotero/
│   ├── vault/
│   └── tests/
├── note/
│   └── <Zotero Collection Name>/
├── 文献索引.md
├── 研究主题索引.md
├── 研究方法索引.md
└── 字段补全检查.md
```

`note/` 初始可以不存在。首次导入 collection 时会自动创建 `note/<collection>/` 和 `_ProcessLog_进度记录.md`。

## 首次配置

### 1. Clone 私有仓库

在第一台电脑：

```powershell
git clone https://github.com/a896024431/Reference-Management.git
cd Reference-Management
```

在第二台电脑也执行同样的 clone。两台电脑各自配置本机 Zotero 路径，不共享 `.local/config.toml`。

### 2. 创建本机配置

```powershell
.\scripts\setup.ps1 -ZoteroDataDir "D:\Zotero"
```

如果 Zotero 默认数据目录在 `%USERPROFILE%\Zotero`，可以直接运行：

```powershell
.\scripts\setup.ps1
```

该命令会创建：

```text
.local/config.toml
```

示例内容：

```toml
[zotero]
data_dir = "D:\\Zotero"
library_id = "library"

[vault]
root = "C:\\Users\\chen\\Desktop\\codex\\Reference-Management"
notes_dir = "note"

[processing]
raw_dir = ".local/raw"
```

`.local/` 被 Git 忽略。每台电脑都应维护自己的本机配置。

### 3. 验证环境

```powershell
.\scripts\verify.ps1
```

验证会运行：

- Vault 索引一致性检查。
- Zotero SQLite fixture 单元测试。
- Collection process log 跳过逻辑测试。
- Skill frontmatter 基础校验。

如果当前 Python 环境没有 `PyYAML`，官方 `skill-creator` 的 `quick_validate.py` 会被跳过；这不影响本仓库脚本使用。

## Zotero 导入工作流

### 1. 查看 collection 中待处理论文

```powershell
python .\scripts\zotero\process_collection.py `
  --collection "你的 Zotero 分类名" `
  --zotero-data-dir "D:\Zotero" `
  --dry-run
```

脚本会读取：

```text
note/<collection>/_ProcessLog_进度记录.md
```

包含 `✅ 成功` 或 `⚠️ 跳过` 的 item key 会被视为已完成，不再重复处理。

### 2. 生成 raw buffer

```powershell
python .\scripts\zotero\process_collection.py `
  --collection "你的 Zotero 分类名" `
  --zotero-data-dir "D:\Zotero"
```

输出文件位于：

```text
.local/raw/<collection>/<item-key>.json
```

这些 JSON 包含：

- `item`
- `metadata`
- `creators`
- `collections`
- `attachments`
- `annotations`
- `notes`
- `fulltext`
- `raw_data_buffer`

`.local/raw/` 不进入 Git。

### 3. 单篇提取

按 Zotero item key 提取：

```powershell
python .\scripts\zotero\extract_item_json.py `
  --item-key ABCD1234 `
  --zotero-data-dir "D:\Zotero" `
  --output .local\raw\ABCD1234.json
```

按标题片段 fallback 查询：

```powershell
python .\scripts\zotero\extract_item_json.py `
  --title "paper title fragment" `
  --zotero-data-dir "D:\Zotero"
```

### 4. 让 Codex 写中文精读笔记

在 Codex 中按顺序使用：

1. `$zotero-data-fetcher`：读取 raw JSON，确认原始 metadata、批注和全文缓存。
2. `$zotero-analytical-writer`：套用 `templates/论文精读模板.md` 生成中文 Obsidian 笔记。
3. `$zotero-collection-manager`：更新 `_ProcessLog_进度记录.md`，标记 `✅ 成功`、`⚠️ 跳过` 或 `❌ 失败`。

笔记建议写入：

```text
note/<collection>/<论文标题>.md
```

每篇笔记必须包含稳定 frontmatter：

```yaml
zotero_key:
collection:
doi:
pdf_link:
theme:
study_area:
data_source:
methodology:
core_variable:
key_finding:
relevance:
```

这些字段会被索引脚本读取。

## Vault 检索工作流

默认使用 `$research-vault-literature-retrieval`。

检索顺序：

1. 先读 `文献索引.md`。
2. 再读 `研究主题索引.md`。
3. 再读 `研究方法索引.md`。
4. 再读 `字段补全检查.md`。
5. 最后用 `rg` 搜索 `note/` 中的具体笔记。

示例：

```powershell
rg -n --glob '*.md' "创新空间|innovation space|GIS|空间分析" .\note
```

回答规则：

- 只基于 Vault 中真实存在的笔记。
- 不把模型记忆、外部常识或 Zotero 未导入内容当作 Vault 证据。
- 证据不足时明确写：`Vault 中未找到足够依据`。

## 刷新索引

修改或新增笔记后运行：

```powershell
python .\scripts\vault\refresh_indexes.py --vault-root .
```

索引文件：

- `文献索引.md`
- `研究主题索引.md`
- `研究方法索引.md`
- `字段补全检查.md`

这些文件是生成物，但会进入 Git，因为它们是两台电脑和 Codex 检索时的共享入口。不要手工长期维护索引页，手工修改会在下次刷新时被覆盖。

检查索引是否过期：

```powershell
python .\scripts\vault\refresh_indexes.py --vault-root . --check
```

## GitHub 双机同步

本仓库已配置远端：

```text
https://github.com/a896024431/Reference-Management.git
```

推荐每次工作前：

```powershell
git pull
```

导入或修改笔记后：

```powershell
python .\scripts\vault\refresh_indexes.py --vault-root .
git status --short
git add AGENTS.md README.md .gitignore .gitattributes *.md note skills templates scripts
git commit -m "Update research vault"
git push
```

默认不要在两台电脑上同时批量导入同一个 Zotero collection。若发生 Markdown 冲突，先人工保留正确版本，再重新刷新索引。

## Git 同步边界

允许同步：

- Markdown 笔记和索引。
- `skills/`
- `templates/`
- `scripts/`
- `AGENTS.md`
- `README.md`
- `.gitignore`
- `.gitattributes`

禁止同步：

- `.local/`
- Zotero `zotero.sqlite`
- Zotero `storage/`
- PDF、EPUB、附件原文。
- `.zotero-ft-cache`
- Obsidian `.obsidian/` workspace 状态。
- `.env`、密钥和证书。
- 临时 raw buffer。

可用命令检查忽略规则：

```powershell
git check-ignore -v .local\config.toml paper.pdf zotero.sqlite .obsidian\workspace.json
```

## Skills 说明

### `zotero-collection-manager`

负责 collection 级批处理：

- 枚举 Zotero collection item。
- 读取 `_ProcessLog_进度记录.md`。
- 跳过已成功或已跳过条目。
- 串行处理未完成论文。
- 处理后刷新 Vault 索引。

### `zotero-data-fetcher`

负责单篇论文原始语料提取：

- metadata
- creators
- collections
- attachments
- annotations
- notes
- full-text cache
- Zotero item/PDF links

原则：保持原文，不翻译、不总结、不改写。

### `zotero-analytical-writer`

负责中文精读笔记写作：

- 使用 `templates/论文精读模板.md`。
- 生成稳定 frontmatter。
- 提炼主题、方法、数据、变量、发现和研究相关性。
- 对结论尽量附原文引用或页码证据。
- 删除无效公式和 OCR 噪音。

### `research-vault-literature-retrieval`

负责 Vault 内检索回答：

- 先索引，后全文。
- 只引用已有笔记证据。
- 明确区分已有证据和缺失证据。

## 常见问题

### Git push 提示 `dubious ownership`

如果仓库由 Codex 沙箱初始化，而 Windows 当前用户推送时被 Git 拒绝，运行：

```powershell
git config --global --add safe.directory C:/Users/chen/Desktop/codex/Reference-Management
```

### Git push 提示没有凭证

确认本机 GitHub 登录状态。可以使用 Git Credential Manager、GitHub CLI 或浏览器授权。凭证只保存在本机，不写入仓库。

### Zotero 数据库正在使用

脚本会复制 `zotero.sqlite` 到临时目录后查询。通常不需要关闭 Zotero。如果复制失败，先关闭 Zotero 再重试。

### 找不到 `.zotero-ft-cache`

可能原因：

- Zotero 尚未为 PDF 建立全文索引。
- PDF 是 linked attachment，不在 Zotero `storage/` 中。
- 附件不是 PDF 或没有可提取文本。

这种情况下仍可使用 metadata、abstract、annotations 和 Zotero notes 写笔记。

### 索引页乱码

文件以 UTF-8 保存。Windows PowerShell 旧终端可能显示乱码，但 Obsidian、VS Code、GitHub 和 Python 脚本会按 UTF-8 正常读取。

### `quick_validate.py` 被跳过

当前 Python 环境缺少 `PyYAML` 时，`verify.ps1` 会跳过 skill-creator 官方验证。仓库自带测试仍会检查每个 `SKILL.md` 的基础 frontmatter。

## 开发与验证

运行全部本地验证：

```powershell
.\scripts\verify.ps1
```

只运行 Python 单元测试：

```powershell
python -m unittest discover -s .\scripts\tests
```

刷新索引：

```powershell
python .\scripts\vault\refresh_indexes.py --vault-root .
```

检查 Git 将提交什么：

```powershell
git status --short
```

## 上游设计来源

本仓库复用了以下两个上游仓库的设计思想，但改为当前 Vault 的配置驱动实现：

- [cheneternity/Zotero-Analytical-Workflow-Skills](https://github.com/cheneternity/Zotero-Analytical-Workflow-Skills)
- [cheneternity/Research-Vault-Literature-Retrieval](https://github.com/cheneternity/Research-Vault-Literature-Retrieval)

核心复用点：

- Zotero collection manager / data fetcher / analytical writer 三段式工作流。
- 从 Zotero 批注和全文缓存构造 raw buffer。
- 中文精读笔记模板化。
- Vault 检索时先读索引，再定位笔记，只基于已有笔记回答。

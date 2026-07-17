# Codex + Obsidian + DeepPaperNote Vault Guide

本仓库的根目录就是 Obsidian Vault 根目录。当前目标很窄：用 Codex 调用仓库内的 DeepPaperNote skill，为单篇论文生成高质量 Obsidian Markdown 深读笔记。

## 默认工作方式

1. 用户给出论文标题、DOI、arXiv ID、URL 或本地 PDF，并要求生成论文笔记时，优先按 DeepPaperNote 工作流处理。
2. DeepPaperNote 是 repo-local skill，路径固定为：
   - `.agents/skills/DeepPaperNote/SKILL.md`
3. Codex 处理论文笔记任务前，必须先读取上面的 `SKILL.md`，并按其中要求读取相关 `references/` 文件。
4. 输出目录采用当前 vault 的扁平论文结构：
   - `Research/<论文标题>/`
5. 每篇论文使用独立文件夹，文件夹内至少包含：
   - `笔记.md`
   - `images/` 目录，即使暂时没有可确认图片也要创建
6. 每次 DeepPaperNote 深度笔记完成、通过校验并保存到 Obsidian 后，最终回复必须询问用户是否需要同步到 GitHub。
   - 只询问，不要在用户确认前自动执行 `git add`、`git commit` 或 `git push`。
   - 用户确认同步后，再按下方 Git 同步边界和常用同步流程执行。

## DeepPaperNote 执行边界

1. Zotero/infiniCloud 是可选联动来源；运行时先探测已有通道，但本仓库不自动安装 Zotero MCP。
2. 通道可用时优先使用可信本地库元数据与附件；不可用时继续使用本地 PDF、DOI、arXiv 或 URL。可用性只记录在 run manifest，禁止写入永久笔记。
3. 不要恢复旧 Zotero 导入脚本、旧静态索引脚本或旧 `note/` 目录工作流。
4. 如果 PDF 或全文证据不足，不要把结果说成完整深读笔记；应明确标记为证据不足或降级草稿。
5. 写入 Obsidian 前按 DeepPaperNote 要求运行 lint 和最终可读性检查。
6. 运行 DeepPaperNote 脚本时，优先使用已验证的系统 Python：
   - `C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe`
   - 该解释器为 Python 3.11.5，已安装 `PyMuPDF/fitz`
   - 当前 shell 默认的 MSYS2 Python 3.12 不含 `fitz`，不适合作为 PDF 处理默认解释器

## Git 同步边界

允许同步：

- `AGENTS.md`
- `README.md`
- `.gitignore`
- `.gitattributes`
- `.agents/skills/DeepPaperNote/`
- `.github/workflows/deeppapernote-v2.yml`
- `Research/*.base`
- `Research/**/*.md`
- `Research/**/images/` 下的常见图片文件

禁止同步：

- Zotero 数据库、storage、PDF、EPUB 和全文缓存
- `.local/`
- `.env`、密钥、证书和本机配置
- Obsidian workspace 状态，如 `.obsidian/`
- 临时输出、Python/Node 缓存和构建产物

## 常用同步流程

```powershell
git pull
git status --short
git add AGENTS.md README.md .gitignore .gitattributes .agents .github Research
git commit -m "Update DeepPaperNote vault"
git push
```

同步前先检查 `git status --short --ignored`，确认没有 PDF、密钥、本机配置或临时构建目录进入 Git。

## DeepPaperNote v2 overlay

当前 Vault 使用 schema v2 overlay。读取 `SKILL.md` 及其必需 references 后，还必须读取：

- `.agents/skills/DeepPaperNote/references/v2-workflow.md`
- `.agents/skills/DeepPaperNote/references/vault-v2.md`

确定性入口使用 `scripts/run_pipeline_final_v2.py`，中间产物默认写入
`.local/deeppapernote/runs/<run_id>/`。正式笔记发布必须通过 v2 合同、证据、插图、
可读性与 Vault 门禁；旧 MVP 脚本只作为兼容回退，不得静默发布 schema v2 笔记。

读者可见的 `笔记.md` 只能展示通过门禁的真实图片及自然图注。`figure_decisions.json`、候选、裁剪、
哈希、审核结果和 `placeholder/omitted` 决定只保存在 `.local/deeppapernote/runs/`；禁止把
`建议位置`、`放置原因`、`当前状态`、`[!figure]` 或其他流程文本写入永久笔记。

Zotero/infiniCloud 是可选 provider：运行时先探测并优先使用可信本地库命中；不可用时回退
本地 PDF、DOI 或 arXiv。可用性只进入 run manifest，不得把 `Zotero not available`
写进永久笔记。本轮不自动安装 Zotero MCP。

### v2 最终发布链

正式入口与门禁依次为：

- `scripts/run_pipeline_final_v2.py`
- `scripts/lint_note_final_v2.py`
- `scripts/build_figure_contact_sheet_v2.py`
- `scripts/record_figure_visual_review_v2.py`
- `scripts/publish_note_final_v2.py`

插图决策改变后必须重建 contact sheet 与视觉复核；任何 `reject` 资源都不能通过人工复核改写为
`inserted`。正式发布只消费与笔记、manifest 和 decisions 哈希一致的通过产物。

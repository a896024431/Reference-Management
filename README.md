# Reference Management

这是一个面向论文精读的 Codex + Obsidian Vault。当前仓库已经从旧的 Zotero 导入原型切换为 repo-local DeepPaperNote 工作流：Codex 读取论文来源，按 DeepPaperNote 的证据优先流程生成高质量 Markdown 笔记，并保存到 Obsidian 可直接打开的目录结构中。

## 本次更新：论文库 v2 与读者体验复核已完成

这次改造的目标是让论文库真正适合在 Obsidian 中阅读和检索，而不只是自动生成一份难读的摘要。现有 9 篇论文已全部迁移到统一的深读格式：每篇顶部先给出“30 秒速览、关键结论、关键数字、适用边界和快速入口”，下方再提供可追溯的精读内容。

2026-07-16 的二次读者体验复核进一步移除了误写入正文的选图与质检过程：正式笔记现在只保留真实图片及自然图注；未插入图片的判断、候选和原因只保存在本地运行记录，不干扰 Obsidian 阅读和检索。

推荐从以下两个入口开始使用：

- [论文导航](Research/论文导航.md)：按主题浏览全部论文。
- [论文库](Research/论文库.base)：用 Obsidian 核心 Bases 查看全部论文、待补图和待复核项目。

本次结果包括：9/9 笔记通过内容、可读性、图片和 Vault 校验；9 篇主文与 7 份补充材料进入同一证据链；39 张图已真实插入。另有 10 个未插图决策仅保留在后台运行记录，不会用低质量裁剪图凑数，也不会以“占位／当前状态”等流程文字打断阅读。

完整的面向使用者说明、范围、验证结果和已知边界见：[更新报告](更新报告.md)。

## 当前结构

```text
.
├── AGENTS.md
├── README.md
├── 更新报告.md
├── .gitignore
├── .gitattributes
├── .agents/
│   └── skills/
│       └── DeepPaperNote/
└── Research/
    ├── 论文导航.md
    ├── 论文库.base
    └── <论文标题>/
        ├── 笔记.md
        └── images/
```

`Research/` 初始可以不存在。第一次生成论文笔记时，DeepPaperNote 会按论文标题创建独立目录。

## 如何使用

1. 用 Obsidian 打开本仓库根目录：
   - `C:\Users\chen\Desktop\codex\Reference-Management`
2. 在 Codex 中给出一篇论文来源，例如：
   - 本地 PDF 路径
   - DOI
   - arXiv ID
   - 论文 URL
   - 论文标题
3. 明确要求生成深度论文笔记，例如：

```text
请用 DeepPaperNote 给这篇论文生成 Obsidian 深度笔记：<论文来源>
```

Codex 会读取 `.agents/skills/DeepPaperNote/SKILL.md`，按其流程解析论文、收集元数据、提取证据、规划图表位置、生成笔记、运行 lint，并保存到：

```text
Research/<论文标题>/
```

## Zotero（可选来源）

Zotero/infiniCloud 已按可选 provider 设计。DeepPaperNote 在运行时探测现有通道：可信本地库
命中优先于标题联网匹配；当前会话没有可调用通道时，继续使用本地 PDF、DOI、arXiv 或
开放元数据。集成状态只进入运行清单，不写入永久笔记，也不会自动安装 Zotero MCP。

不要提交 Zotero 数据库、PDF、附件、全文缓存或本机路径配置。

## DeepPaperNote

DeepPaperNote 已保存为仓库内 skill：

```text
.agents/skills/DeepPaperNote/
```

关键入口：

- `.agents/skills/DeepPaperNote/SKILL.md`
- `.agents/skills/DeepPaperNote/scripts/`
- `.agents/skills/DeepPaperNote/references/`

注意：这是 repo-local 保存，不是全局安装到 `C:\Users\chen\.codex\skills`。如果 Codex 当前环境不会自动发现 repo-local skill，应按 `AGENTS.md` 的路由规则手动读取 `SKILL.md`。

## 环境要求

DeepPaperNote 要求 Python `>=3.10`。当前仓库中已验证可用的解释器是：

```powershell
C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe
```

该解释器为 Python 3.11.5，并且已经安装 `PyMuPDF`。当前 shell 默认的 MSYS2 Python 3.12 不能直接导入 `fitz`，处理 PDF 时优先用上面的系统 Python。

也可以使用 conda，但环境必须是 Python `>=3.10` 且已安装 `PyMuPDF`。当前已检测到的 conda base 是 Python 3.9，不建议直接用于 DeepPaperNote。

论文 PDF 处理依赖 `PyMuPDF`：

```powershell
C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe -c "import fitz; print(fitz.VersionBind)"
```

如果未安装：

```powershell
C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe -m pip install PyMuPDF
```

## Git 同步

推荐同步流程：

```powershell
git pull
git status --short --ignored
git add AGENTS.md README.md .gitignore .gitattributes .agents .github Research
git commit -m "Update DeepPaperNote vault"
git push
```

允许进入 Git 的内容主要是 Markdown 笔记、DeepPaperNote skill、仓库说明和论文笔记图片。PDF、Zotero 数据库、本机配置、密钥、Obsidian workspace 状态、缓存和临时输出都应保持忽略。

## DeepPaperNote v2

当前 Vault 使用单文件双层笔记：每篇仍保存为 `Research/<论文标题>/笔记.md`，顶部提供
“30 秒速览、关键结论、关键数字、适用边界、快速入口”，下方保留带页码证据锚点的完整精读。

确定性管线入口是：

```powershell
C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe `
  .agents\skills\DeepPaperNote\scripts\run_pipeline_final_v2.py --help
```

Obsidian 入口包括 `Research/论文导航.md` 和核心 Bases 文件 `Research/论文库.base`；无需
Dataview。运行产物与迁移备份位于 `.local/deeppapernote/`，并从 Obsidian 搜索中排除。正式笔记不会渲染图像候选、裁剪、审核或发布状态。

Zotero/infiniCloud 作为可选元数据和跳转来源。管线会在运行时探测；不可用时自动使用本地
PDF 和稳定标识符，且不会把集成状态写进永久笔记。

### v2 最终发布链

正式入口与门禁依次为：

- `scripts/run_pipeline_final_v2.py`
- `scripts/lint_note_final_v2.py`
- `scripts/build_figure_contact_sheet_v2.py`
- `scripts/record_figure_visual_review_v2.py`
- `scripts/publish_note_final_v2.py`

插图决策改变后必须重建 contact sheet 与视觉复核；任何 `reject` 资源都不能通过人工复核改写为
`inserted`。正式发布只消费与笔记、manifest 和 decisions 哈希一致的通过产物。

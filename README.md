# Reference Management

这是一个面向论文精读的 Codex + Obsidian Vault。当前仓库已经从旧的 Zotero 导入原型切换为 repo-local DeepPaperNote 工作流：Codex 读取论文来源，按 DeepPaperNote 的证据优先流程生成高质量 Markdown 笔记，并保存到 Obsidian 可直接打开的目录结构中。

## 当前结构

```text
.
├── AGENTS.md
├── README.md
├── .gitignore
├── .gitattributes
├── .agents/
│   └── skills/
│       └── DeepPaperNote/
└── Research/
    └── <论文>/
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
Research/<论文>/
```

## Zotero 状态

当前仓库暂不启用 Zotero 联动，也不保留旧 Zotero 导入脚本。DeepPaperNote 如果在当前 Codex 会话中检测不到 Zotero 工具，应记录 `Zotero not available`，然后继续使用 PDF、DOI、arXiv、URL 或开放元数据来源。

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
git add AGENTS.md README.md .gitignore .gitattributes .agents Research
git commit -m "Update DeepPaperNote vault"
git push
```

允许进入 Git 的内容主要是 Markdown 笔记、DeepPaperNote skill、仓库说明和论文笔记图片。PDF、Zotero 数据库、本机配置、密钥、Obsidian workspace 状态、缓存和临时输出都应保持忽略。

# Reference Management

这是一个用于论文精读的 Codex + Obsidian Vault。向 Codex 提供论文标题、DOI、arXiv ID、URL 或本地 PDF 后，DeepPaperNote 会生成 Markdown 深读笔记，保存到 `Research/<论文标题>/笔记.md`，之后可以直接用 Obsidian 阅读。

## 如何使用

1. 用 Obsidian 打开本仓库根目录。
2. 在 Codex 中提供一篇论文的标题、DOI、arXiv ID、URL 或本地 PDF。
3. 明确要求使用 DeepPaperNote，例如：

```text
请用 DeepPaperNote 给这篇论文生成 Obsidian 深度笔记：<论文来源>
```

Codex 会读取 `.agents/skills/DeepPaperNote/SKILL.md`，按其中的工作流处理论文并保存结果。

## 保存结果

```text
Research/
├── 论文导航.md
├── 论文库.base
└── <论文标题>/
    ├── 笔记.md
    └── images/
```

- [论文导航](Research/论文导航.md)：按主题浏览论文。
- [论文库](Research/论文库.base)：在 Obsidian Bases 中筛选论文。
- 每篇论文使用独立目录；即使没有可靠图片，也会保留 `images/` 目录。

保存前会执行内容和可读性校验。证据不足或流程未完成时，结果会明确标记为草稿或降级内容，不会冒充完整笔记。

## Zotero（可选）

Zotero/infiniCloud 可以作为本地元数据和附件来源。通道可用时优先使用可信的本地结果；不可用时仍可使用本地 PDF、DOI、arXiv、URL 或开放元数据。仓库不会自动安装 Zotero 集成，也不会把临时集成状态写进论文笔记。

## 环境要求

- Python `>=3.10`
- `PyMuPDF`

```powershell
python -m pip install PyMuPDF
```

DeepPaperNote 保存在 `.agents/skills/DeepPaperNote/`。具体工作流由其中的 `SKILL.md` 和相关说明文件定义。

## GitHub 同步

只有在用户确认后才执行同步：

```powershell
git pull --ff-only
git status --short --ignored
git add -- AGENTS.md README.md 更新报告.md .gitignore .gitattributes .agents/skills/DeepPaperNote .github/workflows/deeppapernote-v2.yml Research
git diff --cached --check
git status --short
git commit -m "Update DeepPaperNote vault"
git push
```

同步前检查暂存内容，确保没有 PDF、Zotero 数据库、本机配置、密钥、Obsidian workspace、缓存或临时文件。

项目维护历史见 [更新报告](更新报告.md)。

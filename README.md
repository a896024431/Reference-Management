# Reference Management

这是一个用于论文精读的 Codex + Obsidian Vault。向 Codex 提供本地 PDF、DOI、arXiv ID、可唯一解析的论文标题，或 DOI／arXiv／直接 PDF URL 后，DeepPaperNote 会生成 Markdown 深读笔记，保存到 `Research/<论文标题>/笔记.md`，之后可以直接用 Obsidian 阅读。

## 如何使用

1. 在 Codex 侧边栏先 Pull，使本地仓库与 GitHub 同步。
2. 用 Obsidian 打开本仓库根目录。
3. 在 Codex 中提供论文来源并要求生成 Obsidian 深读笔记；Codex 会自动使用仓库内的 DeepPaperNote 工作流。

支持本地 PDF、DOI、arXiv ID、可唯一解析的标题，以及 DOI／arXiv／直接 PDF URL。普通文章页不抓取 HTML；直接 PDF 无法确认可靠题名时，请改给 DOI 或本地 PDF。

## 保存结果

```text
Research/
├── 论文导航.md
├── 论文库.base
└── <论文标题>/
    ├── 笔记.md
    └── images/    # 仅在有可靠图片时存在
```

- [论文导航](Research/论文导航.md)：进入每篇论文的简洁列表。
- [论文库](Research/论文库.base)：在 Obsidian Bases 中筛选论文。
- 每篇论文使用独立目录；没有可靠图片时只保存 `笔记.md`，避免 Git 无法同步空目录。

只有全文证据、笔记内容和独立复核都通过校验时才会保存正式笔记；来源不完整或关键证据不足时，流程会停止并说明原因。

## Zotero（可选）

Zotero/infiniCloud 可以作为本地元数据和附件来源。通道可用时优先使用可信的本地结果；不可用时仍可使用本地 PDF、DOI、arXiv、可唯一解析的标题或直接 PDF URL。仓库不会自动安装 Zotero 集成，也不会把临时集成状态写进论文笔记。

## 运行环境

Windows 本地统一使用 Miniconda 环境 `deeppapernote`，避免混用系统 Python 和不同来源的 `pip`。首次配置：

```powershell
conda create -n deeppapernote python=3.12 pip -y
conda run --no-capture-output -n deeppapernote python -m pip install ".agents/skills/DeepPaperNote[dev]"
conda env config vars set -n deeppapernote PYTHONUTF8=1 PYTHONIOENCODING=utf-8
```

后续脚本、测试和校验均通过该环境顺序执行。具体命令和工作流由 `.agents/skills/DeepPaperNote/SKILL.md` 定义。

## GitHub 同步

每次任务使用以下顺序：

1. Pull。
2. 让 Codex 修改并完成检查。
3. 检查改动，只暂存 `AGENTS.md` 允许同步的文件。
4. Commit。
5. Push。

Codex 不执行暂存、Commit 或 Push。PDF、本机状态、密钥、缓存和临时文件不得进入 Git。

项目维护历史见 [更新报告](更新报告.md)。

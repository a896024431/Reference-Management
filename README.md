# Reference Management

这是一个用于论文精读的 Codex + Obsidian Vault。向 Codex 提供本地 PDF、DOI、arXiv ID、可唯一解析的论文标题，或 DOI／arXiv／直接 PDF URL 后，DeepPaperNote 会生成 Markdown 深读笔记，保存到 `Research/<论文标题>/笔记.md`，之后可以直接用 Obsidian 阅读。

## 如何使用

1. 用 Obsidian 打开本仓库根目录。
2. 在 Codex 中提供本地 PDF、DOI、arXiv ID、可唯一解析的标题，或 DOI／arXiv／直接 PDF URL。普通出版社文章页不做 HTML 抓取；直接 PDF 必须能从文档元数据或首页确认可靠题名，否则请改给 DOI 或本地 PDF。
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
    └── images/    # 仅在有可靠图片时存在
```

- [论文导航](Research/论文导航.md)：按主题浏览论文。
- [论文库](Research/论文库.base)：在 Obsidian Bases 中筛选论文。
- 每篇论文使用独立目录；没有可靠图片时只保存 `笔记.md`，避免 Git 无法同步空目录。

保存前会执行证据、内容、独立复核和可读性校验。发布时会重新核对本地 PDF、实际页数和图片来源，在同一最终事务中重建论文导航并执行 Vault lint；任一步失败都会恢复旧笔记和导航。全文截断、任一文档 OCR 覆盖不足或关键证据缺失时，流程只报告阻塞，不生成摘要型或降级发布笔记。

## Zotero（可选）

Zotero/infiniCloud 可以作为本地元数据和附件来源。通道可用时优先使用可信的本地结果；不可用时仍可使用本地 PDF、DOI、arXiv、可唯一解析的标题或直接 PDF URL。仓库不会自动安装 Zotero 集成，也不会把临时集成状态写进论文笔记。

## 运行环境

Windows 本地统一使用 Miniconda 环境 `deeppapernote`，避免混用系统 Python 和不同来源的 `pip`。首次配置：

```powershell
conda create -n deeppapernote python=3.12 pip -y
conda run --no-capture-output -n deeppapernote python -m pip install ".agents/skills/DeepPaperNote[dev]"
conda env config vars set -n deeppapernote PYTHONUTF8=1 PYTHONIOENCODING=utf-8
```

后续脚本、测试和校验均通过该环境顺序执行：

```powershell
conda run --no-capture-output -n deeppapernote python <脚本> ...
```

环境启用 Python UTF-8 mode 后，无需再添加 `-X utf8`；Windows 活动代码页仍为 936 也不影响 Python 的默认文本编码。具体工作流由 `.agents/skills/DeepPaperNote/SKILL.md` 和相关说明文件定义。

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

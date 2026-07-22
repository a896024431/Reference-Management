# Reference Management

这是一个用于论文精读的 Codex + Obsidian Vault。Zotero 是文献当前状态的本地镜像来源；DeepPaperNote 只使用 `文献/` 中已镜像的本地 PDF/SI 生成 Markdown 深读笔记。

## 日常使用

1. 在 Codex 侧边栏先 Pull，再用 Obsidian 打开本仓库根目录。
2. 明确选择一项任务：
   - **同步 Zotero**：要求使用 `zotero-pdf-sync` 手动镜像 `我的文库 / ZJU / 课题组`。
   - **做笔记**：明确指定 `文献/` 中一篇本地主文 PDF，要求生成或修改它的笔记。
   - **修改项目**：只维护说明、配置或脚本；已完成笔记默认不处理。

同步没有后台监听，只通过 Zotero Local API 只读访问本机附件，不读写 SQLite，也不需要云端 API key。它会按当前 Zotero 题名和分类移动整篇论文目录，保留其中的 PDF、笔记和图片而不重做笔记。整库同步发现某个已管理条目已不在根范围内时，会把整个目录归档到 `文献/Zotero已删除/`；归档不会进入导航、Base 或 Git，也不会被同步器自动恢复。

DeepPaperNote 没有联网输入：它只处理同一论文目录内的本地 PDF/SI，内部 run 与发布 staging 固定在 `.local/deeppapernote/runs/<run_id>/`。同步、迁移和项目维护都不会自动重新精读、复核或发布完成笔记。

## 文件布局

```text
文献/
├── 论文导航.md
├── 论文库.base
├── <分类>/<论文题名>/
│   ├── <主文或补充材料>.pdf
│   ├── 笔记.md       # 仅精读完成后存在
│   └── images/       # 仅有可靠图片时存在
└── Zotero已删除/     # 本地归档，不进入导航、Base 或 Git
```

直接位于 `课题组` 根分类的条目进入 `文献/未分类/<论文题名>/`。未精读论文仅保留同步后的 PDF；[论文导航](文献/论文导航.md) 与 [论文库](文献/论文库.base) 只服务正式论文树中的已完成笔记。

## 运行环境

Windows 本地统一使用 Miniconda 环境 `deeppapernote`：

```powershell
conda create -n deeppapernote python=3.12 pip -y
conda run --no-capture-output -n deeppapernote python -m pip install ".agents/skills/DeepPaperNote[dev]"
conda env config vars set -n deeppapernote PYTHONUTF8=1 PYTHONIOENCODING=utf-8
```

后续命令均通过该环境顺序执行。详细操作见 `.agents/skills/zotero-pdf-sync/SKILL.md` 与 `.agents/skills/DeepPaperNote/SKILL.md`。

## GitHub 同步

1. Pull。
2. 让 Codex 修改并完成相应检查。
3. 检查改动，只暂存 `AGENTS.md` 允许同步的文件。
4. Commit。
5. Push。

Codex 不执行暂存、Commit 或 Push。PDF、归档树、本机状态、密钥、缓存和临时文件不得进入 Git。项目维护历史见 [更新报告](更新报告.md)。

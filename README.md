# Reference Management

这是一个用于论文精读的 Codex + Obsidian Vault。Zotero 是文献 PDF 的唯一来源：先手动镜像 `我的文库 / ZJU / 课题组` 到本地 Vault，再让 DeepPaperNote 只使用镜像后的本地 PDF 生成 Markdown 深读笔记。

## 三种操作

- **做笔记**：明确指定 `文献/` 中的一篇本地 PDF 后，才对该篇进行精读与笔记处理。
- **同步 Zotero**：只同步目录和 PDF/SI 文件，不读取或修改已有笔记。
- **修改项目**：只检查改动的文档、脚本或配置；已完成笔记默认不处理，只有你明确要求修改某篇时才打开它。

## 如何使用

1. 在 Codex 侧边栏先 Pull，使本地仓库与 GitHub 同步。
2. 用 Obsidian 打开本仓库根目录。
3. 在 Codex 中要求使用 `zotero-pdf-sync` 手动同步 Zotero 的 `我的文库 / ZJU / 课题组`；同步器只复制 PDF 附件（含补充材料）到 `文献/`。
4. 选择 `文献/` 中要精读论文的本地主文 PDF，并要求生成 Obsidian 深读笔记；DeepPaperNote 不会在做笔记时再查询 Zotero。

同步仅在你主动要求时运行，没有后台监听。它通过 Zotero Local API 只读获取本机附件，不读写 Zotero SQLite 数据库，也不需要云端 API key。若 Zotero 中已做笔记论文的题名或分类发生变化，同步器会报告而不会自动移动笔记；Zotero 删除附件也不会自动删除本地 PDF。

直接放在 `课题组` 根分类的条目会进入 `文献/未分类/<论文题名>/`，以保持所有论文均位于分类目录之下。

## 保存结果

```text
文献/
├── 论文导航.md
├── 论文库.base
├── 制备工艺/
│   └── EFLAO/
│       └── <论文题名>/
│           ├── <主文附件名>.pdf
│           ├── <补充材料附件名>.pdf
│           ├── 笔记.md       # 仅精读完成后存在
│           └── images/       # 仅有可靠图片时存在
└── QPC/
    └── <论文题名>/
        └── <主文附件名>.pdf
```

- [论文导航](文献/论文导航.md)：进入每篇已完成笔记的简洁列表。
- [论文库](文献/论文库.base)：在 Obsidian Bases 中筛选已完成笔记。
- 尚未精读的论文目录只保留同步后的 PDF；这类目录是正常状态，不会出现在导航或 Base 中。
- 每篇已完成笔记与其主文、SI 保持同目录；发布笔记不会替换或删除 PDF。

只有全文证据、笔记内容和独立复核都通过校验时才会保存正式笔记；来源不完整或关键证据不足时，流程会停止并说明原因。

## 运行环境

Windows 本地统一使用 Miniconda 环境 `deeppapernote`，避免混用系统 Python 和不同来源的 `pip`。首次配置：

```powershell
conda create -n deeppapernote python=3.12 pip -y
conda run --no-capture-output -n deeppapernote python -m pip install ".agents/skills/DeepPaperNote[dev]"
conda env config vars set -n deeppapernote PYTHONUTF8=1 PYTHONIOENCODING=utf-8
```

后续同步、脚本、测试和校验均通过该环境顺序执行。具体工作流由 `.agents/skills/zotero-pdf-sync/SKILL.md` 与 `.agents/skills/DeepPaperNote/SKILL.md` 定义。

## GitHub 同步

每次任务使用以下顺序：

1. Pull。
2. 让 Codex 修改并完成检查。
3. 检查改动，只暂存 `AGENTS.md` 允许同步的文件。
4. Commit。
5. Push。

Codex 不执行暂存、Commit 或 Push。PDF、本机状态、密钥、缓存和临时文件不得进入 Git。

项目维护历史见 [更新报告](更新报告.md)。

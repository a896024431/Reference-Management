---
name: deeppapernote
description: Generate or explicitly revise an evidence-first Chinese deep-reading note for one named locally mirrored PDF under 文献/ and publish it beside that paper in this Obsidian vault. Use only when the user names a local main PDF (and optional local supplementary PDFs) and asks to create or revise that paper's rigorous Markdown research note with verified figures; do not use for Zotero sync, project maintenance, directory changes, or unchanged completed notes.
---

# DeepPaperNote

一次只处理一篇论文。目标是生成可长期复用、证据可追溯的中文深读笔记，而不是摘要改写。

已完成笔记默认冻结。Zotero 同步、项目维护、目录调整和链接修复不会触发本 skill，也不会要求重新读取 PDF、复核或发布；只有用户明确点名要求新建或修改某篇笔记时才运行。

## 必读路由

- 每次运行先读 `references/workflow.md`，遵守 schema v2 阶段、结果文件和失败策略。
- 制定 note plan 和写正文前读 `references/writing.md`。
- 选择、裁剪或发布图表前读 `references/figures.md`。
- 写入 Obsidian、构建链接或发布前读 `references/vault.md`。

## 输入边界

正式输入只能是 Vault `文献/` 中某篇论文目录的本地主文 PDF；补充材料也从同一目录提供。先用 `$zotero-pdf-sync` 手动镜像 Zotero PDF，再在本地离线完成精读。日常笔记流程不得查询 Zotero API、SQLite、DOI、arXiv、出版社或其他网络来源，也不把运行时状态写进笔记。

主文必须位于 `文献/<一个或多个分类>/<论文目录>/`，并在发布时以其父目录作为正式输出目录。`文献/Zotero已删除/` 是归档，不是输入。无法确认本地主文或需要联网补全文时停止，请用户先完成镜像。

## 明确笔记任务的正式流程

当前 Windows Vault 统一使用 Miniconda 环境 `deeppapernote`。非交互命令使用 `conda run --no-capture-output -n deeppapernote python ...` 并顺序执行，不得混用裸 `python`、裸 `pip` 或临时 Python 环境。环境必须满足 Python 3.10 或更高版本、PyMuPDF/`fitz` 可导入且 Python UTF-8 mode 已启用；其他平台或 CI 使用满足同样条件的等价环境。

按以下顺序运行：

1. `scripts/run_pipeline_v2.py`：只从本地 PDF/SI 建立 record、证据、图片候选和 synthesis bundle，并创建固定的 `.local/deeppapernote/runs/<run_id>/staging/images/`。
2. 模型读取 `synthesis_bundle.json` 并写 `note_plan.json`，再运行 `scripts/validate_note_plan_v2.py`。
3. 模型只在该 run 的 `staging/` 中写 `笔记.md`；若实际插图，只能引用当前 `figure_manifest.json` 中的固定 `images/<文件名>`，不用手工编辑任何 figure JSON。
4. 内部运行 `scripts/plan_figures_v2.py --finalize-note ... --manifest ... --decisions ...`，由正文实际引用的文件名生成最终 decisions。未知、拼错或旧 run 的图片名立即失败。
5. 运行 `scripts/lint_note_v2.py`；主代理显式调用至少一个不同于作者的新子 agent 完成质量与可读性复核，并分别用 `scripts/record_note_review_v2.py` 记录。
6. 只有实际插入图片时，构建 contact sheet 并记录视觉复核；没有插图时跳过这两步。
7. `scripts/publish_note_v2.py`：它从当前 manifest 复制已选图片，在同一最终事务中重建导航、执行 Vault lint 并写完成凭证。

`run_pipeline_v2.py` 的正式调用使用本地 `--input`、必需的 `--vault-root` 和可重复的本地 `--supplement`；保留 `--run-id` 和 `--max-pages`。`run_id` 必须是小写、安全且非 Windows 保留名的单个目录名。所有中间文件固定写入 `.local/deeppapernote/runs/<run_id>/`。

## 不可绕过的强制检查

- paper record、evidence pack 和所有正式处理结果必须共享 `schema_version`、`paper_id`、`run_id`，正式发布状态必须为 `pass` 且 `failures` 为空；review 还必须绑定当前 synthesis/evidence 内容指纹。
- 每次读取 PDF 前后都核对 paper record 中的 SHA-256；正式发布还要求每个文档都有本地 PDF，并重算实际页数，文件变化时停止。
- 任一 PDF 解析失败、全文被 `--max-pages` 截断、任一文档 OCR 文本覆盖低于 60% 或论文类型所需证据缺失时停止；不生成或发布摘要型、degraded 笔记。
- note plan 必须包含唯一结构中的九个字段；所有关键条目必须关联已有的 `evidence_id`。
- 关键结论逐条包含主文或补充材料页码；lint 同时拒绝重复英文题名、多个 H1、失效页内链接和数学环境外裸 LaTeX 命令。
- 主代理不得自行代写复核结果；只有用户明确选择时才改用人工复核，无法调用子 agent 且没有人工复核结果时停止。质量与可读性审阅者必须不同于作者，来源只能是 `subagent` 或 `human`，各项至少 4/5、无遗留问题，并且复核记录必须绑定最终笔记、完整 synthesis 与 passing lint 的内容指纹。
- 正文图片只能是当前 run manifest 中实际存在的固定文件名；发布器核对正文引用、最终选择、复制后的 `images/` 和文件哈希完全一致。未实际插入的候选不做视觉复核。
- 发布程序只接受 `note_status: polished`，要求 evidence、synthesis、note plan 与 frontmatter 的 `paper_type` 一致，并从完整文档和最终图片选择推导、核对 `evidence_level` 与 `figure_status`。
- 待发布目录顶层只能有 `笔记.md` 与 `images/`；`images/` 内只能有支持的图片文件。正式目录没有可靠图片时只保留 `笔记.md`。
- 正文或图片一旦修改，之前的 lint 和复核结果就不再对应当前版本，必须重新执行。

## 输出与 Git

正式目录固定为输入主文同级的 `文献/<分类>/<论文标题>/笔记.md`，有可靠图片时使用同级 `images/`；同目录 PDF/SI 必须原样保留。发布器只管理 `笔记.md` 与 `images/`。本地处理记录只写入 `.local/deeppapernote/published/<run_id>/`。永久笔记不得出现候选 ID、裁剪坐标、内容指纹、QA 状态、可见 placeholder、运行时消息或本机绝对路径。

只有发布器返回包含导航指纹和通过状态 Vault lint 的完成凭证后，才说笔记已完成。它先完整准备新内容，再替换旧版本，并在最终检查失败时恢复旧笔记、导航和审计记录。`rebuild_paper_navigation.py --check` 与 `lint_vault.py` 仍可用于独立维护检查。保存后只提醒用户在 Codex 侧边栏手动同步 GitHub；Codex 不执行 `git add`、`git commit` 或 `git push`。

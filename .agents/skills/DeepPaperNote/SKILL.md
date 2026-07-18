---
name: deeppapernote
description: Generate an evidence-first Chinese deep-reading note for one paper and publish it into an Obsidian vault. Use when the user provides a paper title, DOI, arXiv ID, URL, Zotero item, or local PDF and asks for a rigorous Markdown research note with verified figures.
---

# DeepPaperNote

一次只处理一篇论文。目标是生成可长期复用、证据可追溯的中文深读笔记，而不是摘要改写。

## 必读路由

- 每次运行先读 `references/workflow.md`，遵守 schema v2 阶段、结果文件和失败策略。
- 制定 note plan 和写正文前读 `references/writing.md`。
- 选择、裁剪或发布图表前读 `references/figures.md`。
- 写入 Obsidian、构建链接或发布前读 `references/vault.md`。

## 来源优先级

依次使用用户本地 PDF、可信 Zotero 本地附件、DOI/出版社或 arXiv 开放全文；Semantic Scholar、OpenAlex 等只补元数据。Zotero 只读探测，不自动安装集成，也不把运行时状态写进笔记。

标题检索只有在 DOI、arXiv 或标题/年份去重后剩下唯一可信身份时才能继续；多个候选时停止并请用户提供 DOI、URL 或 PDF。

## 唯一正式流程

当前 Windows Vault 统一使用 Miniconda 环境 `deeppapernote`。非交互命令使用 `conda run --no-capture-output -n deeppapernote python ...` 并顺序执行，不得混用裸 `python`、裸 `pip` 或临时 Python 环境。环境必须满足 Python 3.10 或更高版本、PyMuPDF/`fitz` 可导入且 Python UTF-8 mode 已启用；其他平台或 CI 使用满足同样条件的等价环境。

按以下顺序运行：

1. `scripts/run_pipeline_v2.py`
2. 模型读取 `synthesis_bundle.json` 并写 `note_plan.json`
3. `scripts/validate_note_plan_v2.py`
4. 模型在本次处理的待发布目录中写单文件双层笔记
5. `scripts/lint_note_v2.py`
6. 主代理显式调用至少一个不同于作者的新子 agent，分别完成质量与可读性复核，再用 `scripts/record_note_review_v2.py` 记录
7. `scripts/build_figure_contact_sheet_v2.py`
8. `scripts/record_figure_visual_review_v2.py`
9. `scripts/publish_note_v2.py`
10. `scripts/rebuild_paper_navigation.py`
11. `scripts/lint_vault.py`

`run_pipeline_v2.py` 接受 `--input` 或 `--input-record`，并保留 `--run-id`、`--workdir`、`--vault-root`、`--supplement`、`--offline`、`--max-pages`。所有中间文件写入 `.local/deeppapernote/runs/<run_id>/`。

需要可信输入 JSON 时使用 `scripts/create_input_record.py`；Zotero 命中但未暴露附件路径时可用 `scripts/locate_zotero_attachment.py`。

## 不可绕过的强制检查

- paper record、evidence pack 和所有正式处理结果必须共享 `schema_version`、`paper_id`、`run_id`，正式发布状态必须为 `pass`。
- 任一 PDF 解析失败、全文被 `--max-pages` 截断、OCR 文本覆盖不足或关键证据缺失时停止；不生成或发布摘要型、degraded 笔记。
- note plan 必须包含唯一结构中的九个字段；所有关键条目必须关联已有的 `evidence_id`。
- 关键结论逐条包含主文或补充材料页码；lint 同时拒绝重复英文题名、多个 H1、失效页内链接和数学环境外裸 LaTeX 命令。
- 主代理不得自行代写复核结果；只有用户明确选择时才改用人工复核，无法调用子 agent 且没有人工复核结果时停止。质量与可读性审阅者必须不同于作者，来源只能是 `subagent` 或 `human`，各项至少 4/5、无遗留问题，并且复核记录必须对应最终笔记的内容指纹。
- 每个重要视觉记录 `inserted`、`placeholder` 或 `omitted`；永久笔记只显示可靠图片和自然图注。
- 发布程序只接受 `note_status: polished`，并从完整文档和图像决策推导、核对 `evidence_level` 与 `figure_status`。
- 待发布目录顶层只能有 `笔记.md` 与 `images/`；`images/` 内只能有支持的图片文件。
- 正文或图片一旦修改，之前的 lint 和复核结果就不再对应当前版本，必须重新执行。

## 输出与 Git

正式目录固定为 `Research/<规范标题>/笔记.md` 和同级 `images/`；无可靠图片时也创建空目录。本地处理记录只写入 `.local/deeppapernote/published/<run_id>/`。永久笔记不得出现候选 ID、裁剪坐标、内容指纹、QA 状态、可见 placeholder、运行时消息或本机绝对路径。

只有全部强制检查、安全发布、导航重建和 Vault lint 完成后，才说笔记已完成。安全发布要求新内容完整准备好后才替换旧版本，并在失败时自动恢复。保存后询问用户是否同步 GitHub；确认前不得执行 `git add`、`git commit` 或 `git push`。

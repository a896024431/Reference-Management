---
name: deeppapernote
description: Generate an evidence-first Chinese deep-reading note for one paper and publish it into an Obsidian vault. Use when the user provides a paper title, DOI, arXiv ID, URL, Zotero item, or local PDF and asks for a rigorous Markdown research note with verified figures.
---

# DeepPaperNote

一次只处理一篇论文。目标是生成可长期复用、证据可追溯的中文深读笔记，而不是改写摘要。

## 必读路由

- 每次运行先读 references/workflow.md，遵守 schema v2 阶段、产物和失败策略。
- 在制定 note plan 和写正文前读 references/writing.md。
- 在选择、裁剪或发布图表前读 references/figures.md。
- 在写入 Obsidian、构建链接或发布前读 references/vault.md。

## 来源优先级

依次使用：

1. 用户给出的本地 PDF。
2. 已配置 Zotero 中的可信条目和本地附件。
3. DOI、出版社或 arXiv 的开放全文。
4. Semantic Scholar、OpenAlex 等仅用于补齐元数据。

先只读探测 Zotero；不可用时继续其他来源，不安装集成，也不把运行时可用性写进永久笔记。标题存在歧义时先确认论文身份。

## 正式流程

使用 Python 3.10 或更高版本。正式链只有：

1. scripts/run_pipeline_v2.py
2. 模型读取 synthesis_bundle.json 并写 note_plan.json
3. 模型在 run staging 目录写单文件双层笔记
4. scripts/lint_note_v2.py
5. scripts/record_note_review_v2.py 分别记录质量与可读性复核
6. scripts/build_figure_contact_sheet_v2.py
7. scripts/record_figure_visual_review_v2.py
8. scripts/publish_note_v2.py
9. scripts/rebuild_paper_navigation.py
10. scripts/lint_vault.py

run_pipeline_v2.py 接受 --input 或 --input-record，并保留 --run-id、--workdir、--vault-root、--supplement、--offline、--max-pages。所有运行产物写入 .local/deeppapernote/runs/<run_id>/。

Zotero 命中但未暴露附件路径时，可用 scripts/locate_zotero_attachment.py。需要生成可信输入 JSON 时用 scripts/create_input_record.py。只有具体环境问题阻塞时才用 scripts/check_environment.py。

## 不可绕过的门禁

- 每个 v2 产物必须共享 schema_version、paper_id 和 run_id，并显式记录 status 与 failures。
- PDF 或全文证据不足时停止，或发布首屏明确标记的 degraded 笔记；不得冒充完整深读。
- 脚本负责解析、取证、校验和发布；模型负责论文理解、note plan、技术解释和最终中文写作。
- note plan 必须关联 evidence_id；核心结论必须给出主文或补充材料页码、图表或公式锚点。
- 每个重要图表必须在运行记录中得到 inserted、placeholder 或 omitted 决策。永久笔记只显示可靠的 inserted 图片与自然图注。
- lint 失败时修改并重跑；可读性复核修改正文后必须再次 lint。
- 质量、可读性和图像复核必须绑定最终笔记或图像产物的哈希。正文一旦修改，旧复核立即失效。
- publish_note_v2.py 只向 Research/<规范标题>/ 写入 笔记.md 与 images/，并把紧凑 JSON 审计归档到 .local/deeppapernote/published/<run_id>/。
- 发布后重建导航并运行 Vault lint；任一门禁失败都不得声称完成。

## 输出边界

默认目标是已配置的 Obsidian Vault，目录为 Research/<规范标题>/笔记.md 和同级 images/。即使没有可靠图片，也必须创建 images/。

如果完全没有配置 Vault，先询问用户目标路径；得到明确答复前不要写入 workspace fallback。已配置 Vault 但无写权限时请求权限，不能静默改写到其他目录。

永久笔记不得出现图片候选、裁剪坐标、哈希、QA 状态、隐藏 figure 注释、可见 placeholder、Zotero 可用性或本机绝对路径。

## 完成与 Git

只有解析、取证、note plan、正文、lint、两类文字复核、图像决策、原子发布、导航和 Vault lint 全部完成后，才说笔记已完成并已保存到 Obsidian。中途停止时准确列出已完成、阻塞和待完成阶段。

保存并通过校验后询问用户是否同步 GitHub。用户确认前不得执行 git add、git commit 或 git push；确认后遵守仓库根 AGENTS.md 的 allowlist 和检查流程。

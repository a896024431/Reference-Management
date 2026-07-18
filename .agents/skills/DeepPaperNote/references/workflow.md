# Schema v2 Workflow

## 目录

- 不变量与来源
- 确定性流水线
- 模型阶段
- 发布阶段
- 失败策略
- 产物合同

## 不变量与来源

一次运行只对应一篇论文，但可以包含一份主文和多份补充材料。每个 JSON 产物都必须包含 schema_version、artifact_type、paper_id、run_id、status 和 failures；同一运行的身份必须完全一致。

优先使用用户提供的本地 PDF，其次使用可信 Zotero 附件、DOI/出版社、arXiv 或开放全文。Zotero 只作为可选 provider。不得让标题模糊匹配覆盖可信的本地库命中。

所有中间产物放在 .local/deeppapernote/runs/<run_id>/。正式 Research 目录不得保存运行 manifest。

## 确定性流水线

scripts/run_pipeline_v2.py 依次完成：

1. 解析唯一论文身份。
2. 合并规范元数据。
3. 获取主文和补充材料 PDF。
4. 逐页提取证据并按全文分类论文类型。
5. 提取页面、图片和 caption-anchored 图表资产。
6. 建立 placeholder-first 图表计划和候选排序。
7. 构建无损 synthesis bundle。
8. 写出 note plan 模板和 run manifest。

正常入口参数：

- --input 或 --input-record，二选一。
- --run-id；未提供时生成 UTC 标识。
- --workdir；默认 .local/deeppapernote/runs。
- --vault-root，用于生成安全的 Vault 相对路径。
- --supplement，可重复提供。
- --offline。
- --max-pages；0 表示全文。

确定性流水线完成只表示 synthesis bundle 已准备好，不能表述为笔记完成。

## 模型阶段

模型必须读取 synthesis_bundle.json，先生成短而结构化的 note_plan.json，再写完整笔记。note plan 至少包含论文类型、必须覆盖内容、关键结论、关键数字、章节安排、图表意图及对应 evidence_id。

正文完成后依次执行：

1. lint_note_v2.py。
2. record_note_review_v2.py --kind quality。
3. 完整可读性复核；若正文修改则重跑 lint。
4. record_note_review_v2.py --kind readability，并绑定通过的 lint。
5. 构建 contact sheet、记录图像视觉复核。

## 发布阶段

publish_note_v2.py 在写入前验证：

- paper record、evidence、note plan、lint、质量复核、可读性复核、figure manifest、figure decisions 身份一致。
- 所有文字复核绑定最终笔记 SHA-256。
- 图像复核绑定 manifest、decisions 和 contact sheet。
- 插入图片存在、可解码、哈希匹配，且笔记没有坏 embed 或孤儿图片。
- frontmatter、论文标题、证据等级和 degraded 状态一致。

发布器先在 Research 下准备完整临时目录，再原子替换目标。失败时恢复旧目录；成功后删除事务备份。正式目录只含 笔记.md 与 images/。紧凑 JSON 审计写入 .local/deeppapernote/published/<run_id>/。

随后运行 rebuild_paper_navigation.py 和 lint_vault.py。

## 失败策略

必需阶段失败时只能重试、使用本文件明确允许的降级，或停止并报告。不得跳过阶段、用临时产物冒充发布结果，也不得因速度或便利性改变输出目标。

没有可用全文、关键方法证据或结果证据时 fail closed。允许 degraded 发布时，原因必须同时出现在 frontmatter 和首屏。

## 产物合同

paper_record.json 保存规范元数据和 documents；每份 document 记录角色、来源、路径、哈希和页数。

evidence_pack.json 保存全文论文类型、evidence_units、覆盖率、页面、章节和图表/公式引用。每个 evidence unit 保留 document_id、角色、页码、章节和稳定 evidence_id。

figure_manifest.json 保存碰撞安全的候选资产、来源页、caption/crop 身份、哈希与质量信号。figure_decisions.json 为每个重要视觉记录 inserted、placeholder 或 omitted。

lint_report.json、quality_review.json 和 readability_review.json 必须绑定最终笔记的规范 UTF-8 文本哈希。published audit 另存磁盘文件字节哈希；任何正文编辑都会使旧报告与快照失效。
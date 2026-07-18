# Schema v2 Workflow

## 不变量与来源

一次运行只对应一篇论文，可包含一份主文和多份补充材料。每个 JSON 产物必须包含 `schema_version`、`artifact_type`、`paper_id`、`run_id`、`status` 和 `failures`，同一运行的身份必须完全一致。

优先使用本地 PDF 和可信本地附件。标题检索结果按 DOI、arXiv、规范标题与年份去重；只有一个可信身份时自动接受，否则列出候选并停止。

所有中间产物放在 `.local/deeppapernote/runs/<run_id>/`。正式 `Research/` 不保存运行 manifest。

## 确定性流水线

`scripts/run_pipeline_v2.py` 在创建 run 目录前检查 Python >= 3.10、PyMuPDF、`--max-pages` 和 `--vault-root`，随后：

1. 解析唯一论文身份并合并元数据。
2. 获取主文与补充材料，记录哈希、总页数和安全 Vault 相对路径。
3. 逐页提取全文证据并分类论文类型。
4. 提取图片与 caption-anchored 图表候选。
5. 建立图表计划与候选排序。
6. 构建无损 synthesis bundle。
7. 写出 note-plan 模板和 run manifest。

任一文档解析失败、页数变化、实际截断、OCR 覆盖低于 60%、无页面或论文类型所需证据缺失时，evidence 状态为 `fail` 且流水线非零退出。确定性阶段通过只表示 synthesis bundle 已就绪。

正常参数为 `--input` 或 `--input-record`，以及可选 `--run-id`、`--workdir`、`--vault-root`、可重复 `--supplement`、`--offline`、`--max-pages`；0 表示全文。

## 模型与复核阶段

模型读取 `synthesis_bundle.json` 后生成 `note_plan.json`。该文件必须包含：

- `paper_type`
- `dominant_domain`
- `evidence_ids`
- `must_cover`
- `key_claims`
- `key_numbers`
- `real_comparisons`
- `section_plan`
- `figure_intents`

`must_cover`、`key_claims`、`key_numbers`、`real_comparisons`、`section_plan` 和非空 `figure_intents` 的每个对象都必须有非空 `evidence_ids`；顶层 `evidence_ids` 必须恰好覆盖嵌套绑定。用 `validate_note_plan_v2.py` 对 synthesis bundle 验证后才能写正文。

正文完成后：

1. 运行 `lint_note_v2.py`。
2. 由不同于作者的另一代理或人工完成质量审阅。
3. 用 `record_note_review_v2.py --kind quality --author <作者>` 记录。
4. 完整重读中文；正文有改动则重跑 lint 和质量审阅。
5. 独立完成可读性审阅，再以 `--kind readability --author <作者> --lint <报告>` 记录。
6. 构建 contact sheet 并记录视觉复核。

审阅 JSON 必须给出 `reviewer`、`review_origin: subagent|human`、`independent: true`、分数和空的 `unresolved_issues`。作者与审阅者相同、低于 4/5、遗留问题或哈希过期都会失败。

## 发布阶段

`publish_note_v2.py` 只接受状态为 `pass` 的 paper/evidence/note-plan/lint/review/figure 产物以及 `note_status: polished` 的笔记。它还会：

- 从主文/补充材料推导 `evidence_level: full_text|full_text_supplement`。
- 从 decisions 推导 `figure_status`：无决策为 `none_needed`；只有 placeholder 为 `placeholder_only`；placeholder 与 inserted 并存为 `partial`；无 placeholder 为 `complete`。
- 拒绝 staging 顶层额外文件、`images/` 中的目录或非图片资产。
- 验证图片身份、解码、哈希、embed 与孤儿状态。
- 原子替换 `Research/<标题>/`，失败时恢复旧目录。
- 原子替换 `.local/deeppapernote/published/<run_id>/` 审计；新审计写入失败时保留旧审计。

随后运行导航重建与 Vault lint。

## 失败策略与产物

正式流程没有 `--allow-degraded`、`abstract_only` 或 workspace fallback。证据不完整时只报告阻塞与可补充来源，不生成可发布笔记。

`paper_record.json` 保存元数据和 documents；`evidence_pack.json` 保存全文证据、覆盖率、页码与稳定 evidence ID；figure manifest/decisions 保存候选和最终裁决；lint 与两类文字复核绑定规范 UTF-8 文本哈希；published snapshot 另记录笔记文件和图片字节哈希。

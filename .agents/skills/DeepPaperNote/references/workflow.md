# Schema v2 处理流程

## 不变量与来源

一次运行只对应一篇论文，可包含一份主文和多份补充材料。每个 JSON 结果文件必须包含 `schema_version`、`artifact_type`、`paper_id`、`run_id`、`status` 和 `failures`，同一次处理中的论文与运行编号必须完全一致。

正式流程只使用 `文献/` 中已镜像的本地 PDF。论文身份从本地主文、既有 Vault frontmatter 和本地补充材料核验；不得在日常笔记流程中查询 DOI、arXiv、Zotero 或其他网络来源。

所有中间文件放在 `.local/deeppapernote/runs/<run_id>/`。正式 `文献/` 不保存运行 manifest。

## 确定性处理流程

`scripts/run_pipeline_v2.py` 在创建 run 目录前检查 Python >= 3.10、PyMuPDF、`--max-pages` 和 `--vault-root`，随后：

1. 解析唯一论文身份并合并元数据。
2. 获取主文与补充材料，记录内容指纹、总页数和安全 Vault 相对路径。
3. 逐页提取全文证据并分类论文类型。
4. 提取图片与 caption-anchored 图表候选。
5. 建立图表计划与候选排序。
6. 构建无损 synthesis bundle。
7. 写出 note-plan 模板和 run manifest。

任一文档解析失败、页数变化、实际截断、OCR 覆盖低于 60%、无页面或论文类型所需证据缺失时，evidence 状态为 `fail`，处理流程以非零状态退出。确定性阶段通过只表示 synthesis bundle 已就绪。

正式参数为本地 `--input`、必需的 `--vault-root`、`--offline`、可重复本地 `--supplement`，以及可选 `--run-id`、`--workdir`、`--max-pages`；0 表示全文。`--run-id` 只能是小写、非 Windows 保留名的安全目录名。主文和补充材料必须位于同一 `文献/<分类>/<论文目录>/` 中；禁止元数据查询和 URL 下载。

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

`must_cover`、`key_claims`、`key_numbers`、`real_comparisons`、`section_plan` 和非空 `figure_intents` 的每个对象都必须有非空 `evidence_ids`；顶层 `evidence_ids` 必须恰好覆盖各条目关联的证据编号。用 `validate_note_plan_v2.py` 对 synthesis bundle 验证后才能写正文。

正文完成后：

正常的一次性交付默认使用子 agent 复核。主代理必须通过可用的多代理工具显式调用至少一个不同于作者的新子 agent，并把笔记、synthesis bundle 与复核要求交给它；主代理不得自行填写或代写审阅 JSON。质量与可读性可由同一个子 agent 分别完成并形成两份记录。只有用户明确选择时才等待人工复核；无法调用子 agent 且没有人工复核结果时停止，不得发布。

1. 运行 `lint_note_v2.py`。
2. 由不同于作者的另一代理或人工完成质量审阅。
3. 用 `record_note_review_v2.py --kind quality --author <作者>` 记录。
4. 完整重读中文；正文有改动则重跑 lint 和质量审阅。
5. 独立完成可读性审阅，再以 `--kind readability --author <作者> --lint <报告>` 记录。
6. 构建 contact sheet 并记录视觉复核。

审阅 JSON 必须给出 `reviewer`、`review_origin: subagent|human`、`independent: true`、分数和空的 `unresolved_issues`。作者与审阅者相同、低于 4/5、质量复核未覆盖至少三条不同结论、存在遗留问题，或笔记、完整 synthesis、evidence、passing lint 已修改而复核不再对应当前版本，都会失败。

## 发布阶段

`publish_note_v2.py` 只接受状态为 `pass` 且 failures 为空的 paper/evidence/synthesis/note-plan/lint/review/figure 处理结果以及 `note_status: polished` 的笔记。它还会：

- 重新核验逐文档 evidence coverage、论文类型所需证据、evidence ID、本地 PDF 的读取前后 SHA-256 与实际页数，以及复核记录与当前完整 synthesis/evidence/lint 的内容绑定。
- 从主文/补充材料推导 `evidence_level: full_text|full_text_supplement`。
- 从 decisions 推导 `figure_status`：无决策为 `none_needed`；只有 placeholder 为 `placeholder_only`；placeholder 与 inserted 并存为 `partial`；无 placeholder 为 `complete`。
- 拒绝待发布目录顶层的额外文件，以及 `images/` 中的目录或非图片文件。
- 验证图片的 document/page/稳定身份、实际解码、内容指纹，并要求正文图片恰好等于已插入且通过视觉复核的本地图片集合；拒绝远程、data URI 与 HTML 图片。
- 从主文的 Vault 相对路径定位 `文献/<分类>/<论文目录>/`，只安全替换 `笔记.md` 与 `images/`；同目录 PDF/SI 不得被移动、删除或改写。已有笔记时仍须由 DOI/arXiv 或 authors+year 证明同一论文，失败时恢复受管内容。
- 原子重建导航并执行严格 Vault lint；失败时恢复旧笔记和导航。
- 最终检查通过后才安全更新 `.local/deeppapernote/published/<run_id>/`；新记录写入失败时恢复旧版本。
- 写出带导航指纹和 Vault lint 摘要的最终完成凭证；清理遗留 backup 失败只记录警告，不把已完成发布误报为失败。

独立维护时可另外运行导航 `--check` 与 Vault lint，但它们不再是正常发布后依赖人工补跑的步骤。

## 失败策略与结果文件

正式流程没有 `--allow-degraded`、`abstract_only` 或 workspace fallback。证据不完整时只报告阻塞与可补充来源，不生成可发布笔记。

`paper_record.json` 保存元数据和 documents；`evidence_pack.json` 保存全文证据、覆盖率、页码与稳定 evidence ID；figure manifest/decisions 保存候选和最终决定；lint 与两类文字复核都记录所检查笔记和证据内容指纹；发布版本记录保存 LF 规范化笔记和图片的字节级内容指纹，以及导航与 Vault lint 的完成状态。

# Schema v2 处理流程

## 输入与中间结果

一次运行对应一篇论文，可含一份主文与多份 SI。正式输入只来自 `文献/` 的本地 PDF；不得联网补全或查询 Zotero。所有中间结果写入 `.local/deeppapernote/runs/<run_id>/`。

`run_pipeline_v2.py` 依次建立 paper record、全文 evidence pack、少量视觉页和紧凑的 synthesis bundle。交给代理的 bundle 只保留一份带 evidence ID 的正文，不再按类型、章节或候选清单重复复制全文。任一 PDF 解析失败、全文截断、OCR 文字覆盖低于 60% 或论文类型所需证据缺失时停止。

视觉页来自含图注或图号引用的 PDF 页面，保留在 run 的 `visual-pages/`。它们只供代理阅读曲线、示意图或显微图，既不裁切成图片资产，也不进入笔记、发布目录或 Git。

## 写作与第二读

模型读取 `synthesis_bundle.json`，必要时查看 `visual_pages.json` 列出的本地页面，再生成 `note_plan.json`。计划必须包含：

- `paper_type`
- `dominant_domain`
- `evidence_ids`
- `must_cover`
- `key_claims`
- `key_numbers`
- `real_comparisons`
- `section_plan`

所有关键条目都要关联 evidence ID；顶层 evidence ID 必须恰好覆盖各条目实际引用的证据。

正文只写入 `staging/笔记.md`，必须是纯文字 Markdown，不得使用图片 embed。完成后由另一代理或人工做一次第二读。它在 `second_review.input.json` 中记录：

- reviewer 与 `review_origin: subagent|human`
- 七项 1—5 分评分
- 空的 `unresolved_issues`
- 至少三条 `passages_checked`，每条含正文实际存在的 Markdown heading、该标题下唯一可定位的 quote 和 evidence IDs；三条 quote 必须属于不同段落

第二读是实际流程要求；JSON 只绑定笔记和证据内容，不声称自行证明代理身份。

作者和第二读使用角色隔离的上下文：作者读取当前 run 的完整本地证据，第二读不继承作者的聊天历史，直接从同一 run 读取笔记、PDF 证据和视觉页。交接只传递 run 路径、任务和必要哈希，不复制完整工件正文；完整证据仍保留在 `.local/`，因此上下文精简不会降低证据覆盖。

## 统一发布

运行：

```text
publish_note_v2.py --vault <Vault> --run-id <run_id> --author <作者>
```

发布器固定读取当前 run 的 paper record、evidence、visual pages、synthesis、note plan、staging note 与第二读输入。它会：

- 运行最终笔记 lint；
- 绑定并验证第二读；
- 重新核验 PDF 的 SHA-256、页数和证据；
- 只替换同级 `笔记.md`，不触碰历史笔记已有的 `images/`；
- 原子重建 `文献/论文导航.md`；
- 将当前 run 的审计 JSON 写入 `.local/deeppapernote/published/<run_id>/`。

发布只检查当前笔记和导航；全 Vault lint 由 CI 或用户明确要求的维护任务执行。

## 失败策略

没有 abstract-only、degraded 发布或 workspace fallback。正文、note plan、第二读或本地 PDF 任一不满足门禁时，保留 run 中的诊断并停止；不会改动正式笔记或 PDF。

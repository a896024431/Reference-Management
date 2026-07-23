---
name: deeppapernote
description: Generate or explicitly revise an evidence-first Chinese deep-reading note for one named locally mirrored PDF under 文献/ and publish its text-only Markdown note beside that paper in this Obsidian vault. Use only when the user names a local main PDF (and optional local supplementary PDFs) and asks to create or revise that paper's rigorous note; do not use for Zotero sync, project maintenance, directory changes, or unchanged completed notes.
---

# DeepPaperNote

一次只处理一篇论文，生成可追溯的中文深读笔记。已完成笔记默认冻结；同步、目录调整和项目维护都不会触发本 skill。

## 必读路由

- 每次运行先读 `references/workflow.md`。
- 制定 note plan 和写正文前读 `references/writing.md`。
- 写入或发布前读 `references/vault.md`。

## 输入边界

正式输入只能是同一论文目录内、已镜像到 `文献/` 的主文 PDF 与可选 SI。不得查询 Zotero、SQLite、DOI、arXiv、出版社或其他网络来源。`文献/Zotero已删除/` 不是输入。

## 正式流程

使用 Miniconda `deeppapernote` 环境，并顺序运行命令。

1. 运行 `scripts/run_pipeline_v2.py --input ... --vault-root ...`。它提取全文证据，并在当前 `.local/deeppapernote/runs/<run_id>/visual-pages/` 临时渲染少量含图页，供代理理解图形信息。
2. 代理读取紧凑的 `synthesis_bundle.json`（每段 evidence 正文只保留一份），必要时查看 `visual_pages.json` 中列出的本地页面图片；写 `note_plan.json` 并用 `validate_note_plan_v2.py` 验证。
3. 代理只在当前 run 的 `staging/笔记.md` 写纯文字 Markdown。不得嵌入、复制或发布任何图片。
4. 由不同于作者的另一代理或人工完成一次第二读校对：至少引用各自 Markdown 标题下的三处不同正文段落，并核对对应 evidence ID。校对结果先写为 `second_review.input.json`。
5. 运行 `publish_note_v2.py --vault <Vault> --run-id <run_id> --author <作者>`。它用固定 run 路径执行 lint、绑定第二读、原子替换笔记并重建论文导航。

`run_id` 必须是小写、安全且非 Windows 保留名的单个目录名。所有中间结果都在 `.local/deeppapernote/runs/<run_id>/`。

## 代理上下文

- 当前 run 的受验证证据工件和本地 PDF 是唯一证据来源；代理之间只传递当前 run 路径、角色任务和必要的文件哈希，不复制聊天历史、调试输出或完整 Markdown。
- 作者直接读取当前 run 的 evidence、synthesis 和视觉页；第二读代理使用不继承作者对话历史的独立上下文（`fork_turns: none`），直接读取最终笔记和同一批本地证据。
- 完整证据保留在 `.local/` 中，不因上下文精简而删减；不要用 `Get-Content -Raw` 或等价方式把完整 JSON、PDF 提取文本或笔记回显到对话中。

## 强制检查

- 每次读取 PDF 前后核对 SHA-256；解析失败、截断、OCR 覆盖不足或关键证据缺失时停止。
- note plan 的关键条目必须关联现有 evidence ID；关键结论必须有主文或补充材料页码。
- 第二读必须不同于作者、分数均不低于 4/5、无遗留问题，并引用当前笔记中各自标题下真实存在的三个不同段落。它是流程上的第二次校对，不把 JSON 字段误称为可证明的代理独立性。
- 正式笔记不得含图片 embed、运行路径、处理状态或本机绝对路径。
- 发布器只管理 `笔记.md`；既有笔记中的 `images/` 是历史读者内容，新流程不会创建或修改它们。
- 发布后重建 `文献/论文导航.md`；全 Vault lint 是 CI 或明确维护任务，不阻塞单篇发布。

## 输出与 Git

输出固定为主文同级的 `笔记.md`。处理记录和临时视觉页面只写入 `.local/`，不进入 Git。保存后只提醒用户在 Codex 侧边栏手动同步 GitHub；Codex 不执行 `git add`、`git commit` 或 `git push`.

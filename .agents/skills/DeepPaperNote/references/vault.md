# Obsidian Vault 规则

## 永久目录

Zotero PDF 先由 `$zotero-pdf-sync` 镜像到 Vault。新流程每篇论文为：

    文献/<一个或多个分类>/<canonical title>/
      <main>.pdf
      <SI>.pdf                 # 可选
      笔记.md                  # 精读完成后存在

DeepPaperNote 新流程只发布 `笔记.md`。运行记录、临时视觉页、审计 JSON 和 rollback 都放在 `.local/`。

历史笔记可能仍有 `images/` 和 `figure_status`；它们是只读兼容内容，Obsidian 可继续显示，Vault lint 也允许它们存在。新流程不创建、复制或校验这些图片；重新发布某篇历史笔记时，只替换 `笔记.md`，保留其已有图片目录。

`文献/Zotero已删除/` 是整库同步产生的本地归档，不是发布论文树；DeepPaperNote、导航、Base 和 Git 都忽略它。

## Frontmatter

新笔记必需属性为 `type: paper`、`title`、`title_zh`、`authors`、`year`、`venue`、`domain`、2 至 6 个 `topics`、`paper_type`、`evidence_level`、`note_status`、`aliases` 与 `papers/` 小写层级 tags。

`paper_type`、`evidence_level` 与 `note_status` 的枚举由正式笔记 lint 验证，CI 的 Vault lint 也会复查。正式发布只接受 `note_status: polished`。旧笔记的 `figure_status` 可保留，但不再是新输出字段或 Base 筛选条件。

本地来源只允许 Vault 相对路径；永久笔记不依赖 Zotero key、URI 或本机绝对路径。

## 链接与导航

`文献/论文库.base` 提供属性筛选；`文献/论文导航.md` 提供静态直接链接。发布器只重建导航，单篇发布不会因无关旧笔记的全库 lint 问题而回滚。全 Vault lint 在 CI 或明确维护任务中运行。

## 安全发布

发布主文必须位于 `文献/<分类>/<论文目录>/`，并以主文父目录为目标。发布器在 `.local/` 准备并验证新 `笔记.md`，再只替换这份受管笔记；同目录 PDF/SI 的路径、名称和字节不得发生变化。

已有笔记时会验证论文身份。最终检查或审计写入失败时恢复原笔记、历史图片目录和导航；不清理论文目录或附件。

## 本地与 Git 边界

`.local/`、`.obsidian/`、PDF、`文献/Zotero已删除/`、Zotero 数据库、密钥、缓存与临时文件不进入 Git。Git 同步根说明、两个 repo-local skill、正式 workflow、论文导航、论文笔记、Base 和历史笔记使用的常见图片。

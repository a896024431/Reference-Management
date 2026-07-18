# Obsidian Vault Contract

## 永久目录

每篇论文固定为：

    Research/<canonical title>/
      笔记.md
      images/

标题只移除文件系统不允许的字符，不添加领域目录。无可靠图片时也创建空 `images/`。正式目录不得包含 manifest、候选图、PDF、非图片资产或临时文件。

## Frontmatter

必需属性为 `type: paper`、`title`、`title_zh`、`authors`、`year`、`venue`、`domain`、2 至 6 个受控 `topics`、`paper_type`、`evidence_level`、`note_status`、`figure_status`、`aliases` 与 `papers/` 小写层级 tags。

`paper_type` 允许 `experimental_physics`、`theoretical_physics`、`materials_fabrication`、`ai_method`、`benchmark`、`clinical`、`humanities`、`survey`、`generic`。

`evidence_level` 只允许 `full_text`、`full_text_supplement`。`note_status` 的 Vault 枚举保留 `draft`、`reviewed`、`polished`、`degraded` 以兼容历史手工内容，但正式发布器只接受 `polished`。`figure_status` 允许 `complete`、`partial`、`placeholder_only`、`none_needed`。

发布器从已完整解析的 documents 推导 evidence level，从 figure decisions 推导 figure status；手写值不一致时拒绝发布。

`date`、`doi`、`arxiv`、`source_url`、`local_pdf`、`supplement_pdfs`、`methods`、`materials`、`code_url`、`project_url`、`zotero_key`、`zotero_uri` 只在有值时写入。本地来源只允许 Vault 相对路径。

## 链接与导航

先按目录标题、`title`、`title_zh`、aliases 和 DOI 建索引。唯一命中时使用：

    [[Research/Canonical Paper Title/笔记|可读标题]]

没有唯一命中时保留纯文本，不猜测路径。`Research/论文库.base` 是属性数据库；`Research/论文导航.md` 嵌入 Base 并提供真实链接。

## 原子发布与审计

发布前 staging 顶层必须恰好是 `笔记.md` 与 `images/`。发布器在 `Research/` 下准备完整临时目录后原子替换，失败时恢复旧目录。

发布使用的 paper/evidence/note-plan/lint/reviews/figure/contact-sheet/visual-review/report 归档到：

    .local/deeppapernote/published/<run_id>/

审计也采用临时目录和原子替换；新审计失败时恢复旧审计。snapshot 同时记录规范 UTF-8 文本哈希、磁盘笔记字节哈希与每张图片字节哈希。任何正文或图片变化都会使旧审计过期。

## 本地与 Git 边界

`.local/`、`.obsidian/`、PDF、Zotero 数据库、密钥、缓存与临时文件不进入 Git。Git 只同步根说明、DeepPaperNote skill、正式 workflow、Research Markdown、Base 和常见图片。

每次发布后运行 `rebuild_paper_navigation.py` 与 `lint_vault.py`。Vault lint 必须通过属性枚举、绝对路径、链接、embed、图片解码、孤儿图片、导航覆盖和读者可见流程元数据检查。

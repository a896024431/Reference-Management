# Obsidian Vault 规则

## 永久目录

每篇论文固定为：

    Research/<canonical title>/
      笔记.md
      images/

标题只移除文件系统不允许的字符，不添加领域目录。无可靠图片时也创建空 `images/`。正式目录不得包含 manifest、候选图、PDF、非图片资产或临时文件。

## Frontmatter

必需属性为 `type: paper`、`title`、`title_zh`、`authors`、`year`、`venue`、`domain`、2 至 6 个受控 `topics`、`paper_type`、`evidence_level`、`note_status`、`figure_status`、`aliases` 与 `papers/` 小写层级 tags。

`paper_type` 允许 `experimental_physics`、`theoretical_physics`、`materials_fabrication`、`ai_method`、`benchmark`、`clinical`、`humanities`、`survey`、`generic`。

`evidence_level` 只允许 `full_text`、`full_text_supplement`。`note_status` 的 Vault 枚举保留 `draft`、`reviewed`、`polished`、`degraded` 以兼容历史手工内容，但正式发布程序只接受 `polished`。`figure_status` 允许 `complete`、`partial`、`placeholder_only`、`none_needed`。

发布程序从已完整解析的 documents 推导 evidence level，从 figure decisions 推导 figure status；手写值不一致时拒绝发布。

`date`、`doi`、`arxiv`、`source_url`、`local_pdf`、`supplement_pdfs`、`methods`、`materials`、`code_url`、`project_url`、`zotero_key`、`zotero_uri` 只在有值时写入。本地来源只允许 Vault 相对路径。

## 链接与导航

先按目录标题、`title`、`title_zh`、aliases 和 DOI 建索引。唯一命中时使用：

    [[Research/Canonical Paper Title/笔记|可读标题]]

没有唯一命中时保留纯文本，不猜测路径。`Research/论文库.base` 是属性数据库；`Research/论文导航.md` 嵌入 Base 并提供真实链接。

## 安全发布与本地记录

发布前，待发布目录顶层必须恰好是 `笔记.md` 与 `images/`。发布程序先在 `Research/` 下准备完整的新目录，确认准备完成后再替换旧目录；失败时恢复旧目录。

发布使用的 paper/evidence/note-plan/lint/reviews/figure/contact-sheet/visual-review/report 归档到：

    .local/deeppapernote/published/<run_id>/

本地发布记录也先写入临时目录，完整写好后再替换旧记录；新记录写入失败时恢复旧记录。发布版本记录同时保存统一编码后的笔记内容指纹、磁盘笔记的字节级内容指纹和每张图片的字节级内容指纹。正文或图片发生变化后，旧记录不再对应当前文件。

## 本地与 Git 边界

`.local/`、`.obsidian/`、PDF、Zotero 数据库、密钥、缓存与临时文件不进入 Git。Git 只同步根说明、DeepPaperNote skill、正式 workflow、Research Markdown、Base 和常见图片。

每次发布后运行 `rebuild_paper_navigation.py` 与 `lint_vault.py`。Vault lint 必须通过属性枚举、绝对路径、链接、embed、图片能否正常打开、未被引用图片、导航覆盖和读者可见流程元数据检查。

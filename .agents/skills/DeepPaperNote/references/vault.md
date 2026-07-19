# Obsidian Vault 规则

## 永久目录

每篇论文固定为：

    Research/<canonical title>/
      笔记.md
      images/  # 仅在有可靠图片时存在

标题只移除文件系统不允许的字符，不添加领域目录。同名目录只有在强标识相同，或 authors 与 year 都一致时才允许更新。无可靠图片时只保留 `笔记.md`，因为 Git 不同步空目录。`Research/` 顶层不得残留无笔记目录、发布临时目录或额外文件；正式目录不得包含 manifest、候选图、PDF、非图片资产或临时文件。

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

发布前，待发布目录顶层必须恰好是 `笔记.md` 与 `images/`。发布程序先在 `Research/` 下准备完整的新目录，确认准备完成后再替换旧目录；随后重算最终笔记与图片指纹、原子重建导航并执行严格 Vault lint。最终检查或审计写入失败时恢复旧论文目录和导航。backup 不得放入 `Research/`，报告写在 Vault 内时只能进入 `.local/`；正式目录在没有发布图片时省略 `images/`。

发布使用的 paper/evidence/note-plan/lint/reviews/figure/contact-sheet/visual-review/report 归档到：

    .local/deeppapernote/published/<run_id>/

本地发布记录也先写入临时目录，完整写好后再替换旧记录；新记录写入失败时恢复旧记录。发布器把笔记统一写成 UTF-8/LF，并保存笔记、图片与导航的字节级内容指纹及 Vault lint 摘要。正文、图片或导航发生变化后，旧记录不再对应当前文件。

## 本地与 Git 边界

`.local/`、`.obsidian/`、PDF、Zotero 数据库、密钥、缓存与临时文件不进入 Git。Git 只同步根说明、DeepPaperNote skill、正式 workflow、论文导航、论文笔记、Base 和笔记使用的常见图片。

正常发布事务内部运行导航重建与 Vault lint；独立维护时使用 `rebuild_paper_navigation.py --check` 和 `lint_vault.py`。Vault lint 必须通过属性枚举、目录形状、绝对路径、链接、embed、图片实际解码、孤儿图片、导航覆盖和读者可见流程元数据检查。

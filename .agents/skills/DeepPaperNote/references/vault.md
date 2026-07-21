# Obsidian Vault 规则

## 永久目录

Zotero PDF 先由 `$zotero-pdf-sync` 镜像到 Vault。`我的文库 / ZJU / 课题组` 对应 `文献/`，每篇论文为：

    文献/<一个或多个分类>/<canonical title>/
      <main>.pdf
      <SI>.pdf                 # 可选，可有多份
      笔记.md                  # 仅已完成精读时存在
      images/                  # 仅在有可靠图片时存在

分类目录和只含 PDF 的论文目录都是合法的，不生成空笔记目录。题名只移除文件系统不允许的字符；同分类出现相同题名时同步器会使用稳定 Zotero key 区分目录。正式笔记目录只允许 PDF、`笔记.md` 与可选 `images/`；不得包含 manifest、候选图、运行时 JSON、其他文档或临时文件。

`Research/` 是迁移前的旧布局；正式 Vault 中不得残留它。

## Frontmatter

必需属性为 `type: paper`、`title`、`title_zh`、`authors`、`year`、`venue`、`domain`、2 至 6 个受控 `topics`、`paper_type`、`evidence_level`、`note_status`、`figure_status`、`aliases` 与 `papers/` 小写层级 tags。

`paper_type` 允许 `experimental_physics`、`theoretical_physics`、`materials_fabrication`、`ai_method`、`benchmark`、`clinical`、`humanities`、`survey`、`generic`。

`evidence_level` 只允许 `full_text`、`full_text_supplement`。`note_status` 的 Vault 枚举保留 `draft`、`reviewed`、`polished`、`degraded` 以兼容历史手工内容，但正式发布程序只接受 `polished`。`figure_status` 允许 `complete`、`partial`、`placeholder_only`、`none_needed`。

发布程序从已完整解析的本地 documents 推导 evidence level，从 figure decisions 推导 figure status；手写值不一致时拒绝发布。

`date`、`doi`、`arxiv`、`source_url`、`local_pdf`、`supplement_pdfs`、`methods`、`materials`、`code_url`、`project_url` 只在有值时写入。本地来源只允许 Vault 相对路径；正式笔记不依赖 Zotero key、URI 或本机绝对路径。

## 链接与导航

先按目录标题、`title`、`title_zh`、aliases 和 DOI 建索引。唯一命中时使用：

    [[文献/QPC/Canonical Paper Title/笔记|可读标题]]

没有唯一命中时保留纯文本，不猜测路径。`文献/论文库.base` 是属性数据库；`文献/论文导航.md` 嵌入 Base 并提供真实链接。

## 安全发布与本地记录

发布主文必须位于 `文献/<分类>/<论文目录>/`，并以该主文的父目录作为目标。发布器先在 `.local/` 中准备和验证新的 `笔记.md` 与 `images/`，再仅替换这两个受管内容；同目录 PDF/SI 的路径、字节和名称不得发生变化。已有笔记时会验证论文身份；首次向仅含 PDF 的目录发布合法。

最终检查或审计写入失败时只恢复旧笔记和图片，绝不清理论文目录或附件。backup 不得放入 `文献/`，报告写在 Vault 内时只能进入 `.local/`。

发布使用的 paper/evidence/note-plan/lint/reviews/figure/contact-sheet/visual-review/report 归档到：

    .local/deeppapernote/published/<run_id>/

本地发布记录也先写入临时目录，完整写好后再替换旧记录；新记录写入失败时恢复旧记录。发布器把笔记统一写成 UTF-8/LF，并保存笔记、图片与导航的字节级内容指纹及 Vault lint 摘要。正文、图片或导航发生变化后，旧记录不再对应当前文件。

## 本地与 Git 边界

`.local/`、`.obsidian/`、PDF、Zotero 数据库、密钥、缓存与临时文件不进入 Git。Git 只同步根说明、两个 repo-local skill、正式 workflow、论文导航、论文笔记、Base 和笔记使用的常见图片。

正常发布事务内部运行导航重建与 Vault lint；独立维护时使用 `rebuild_paper_navigation.py --check` 和 `lint_vault.py`。Vault lint 必须通过属性枚举、目录形状、绝对路径、链接、embed、图片实际解码、孤儿图片、导航覆盖和读者可见流程元数据检查。

# Obsidian Vault Contract

## 永久目录

每篇论文固定为：

    Research/<canonical title>/
      笔记.md
      images/

标题只移除本地文件系统不允许的字符，不添加领域目录。即使没有图片也创建 images/。Research 正式目录不得包含 manifests、候选图、PDF 或临时文件。

## Frontmatter

每篇笔记必须包含：

- type: paper
- title、title_zh
- authors、year、venue
- domain 与 2 至 6 个受控 topics
- paper_type
- evidence_level
- note_status
- figure_status
- aliases，至少一个拉丁字母别名和一个中文别名
- 以 papers/ 开头的小写层级 tags

paper_type 允许 experimental_physics、theoretical_physics、materials_fabrication、ai_method、benchmark、clinical、humanities、survey、generic。

evidence_level 允许 abstract_only、full_text、full_text_supplement。note_status 允许 draft、reviewed、polished、degraded。figure_status 允许 complete、partial、placeholder_only、none_needed。

date、doi、arxiv、source_url、local_pdf、supplement_pdfs、methods、materials、code_url、project_url、zotero_key、zotero_uri 仅在有值时写入。所有本地来源路径必须为 Vault 相对路径。

使用 vault.py 的 frontmatter 渲染与解析函数，不手写嵌套 YAML。

## 链接与导航

先按规范目录标题、title、title_zh、aliases 和 DOI 建立索引，再解析引用。唯一命中时使用：

    [[Research/Canonical Paper Title/笔记|可读标题]]

没有唯一命中时保留纯文本引用，不能猜测路径。

Research/论文库.base 是属性数据库入口；Research/论文导航.md 嵌入 Base 并提供每篇论文的真实链接。Base 保持全部论文、待补图、待复核、按主题四个视图，不引入 Dataview。

## 原子发布与本地审计

publish_note_v2.py 先验证完整 staging，再在 Research 下准备临时目录并原子替换。失败时恢复旧目录；成功后清理事务备份。

正式目录只复制 笔记.md 和 images/。发布使用的 paper record、evidence、note plan、lint、文字复核、figure manifest/decisions、contact sheet、视觉复核和 publish report 以 JSON 归档到：

    .local/deeppapernote/published/<run_id>/

审计 snapshot 同时记录规范 UTF-8 文本哈希 note_sha256、磁盘文件字节哈希 note_file_sha256，以及每张图片的字节哈希。lint 和文字复核以 note_sha256 为准；磁盘快照核验同时检查两种笔记哈希，避免 Windows 换行符造成误判。任何对应哈希不一致都表示审计过期，必须重跑校验。

## 本地与 Git 边界

Obsidian 的 userIgnoreFilters 应排除 .local/、tmp/ 和 DeepPaperNote_output/。.obsidian/ 保持本机私有。

Git 只同步根说明、DeepPaperNote skill、正式 workflow、Research Markdown、Base 和常见图片。不得同步 PDF、Zotero 数据库、.local、.obsidian、密钥、缓存或临时文件。

每次发布后运行 rebuild_paper_navigation.py，再运行 lint_vault.py。Vault lint 必须通过属性枚举、绝对路径、运行时消息、链接、embed、图片解码、孤儿图片、导航覆盖和读者可见流程元数据检查。

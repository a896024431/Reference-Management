# Codex + Obsidian + DeepPaperNote Vault Guide

本仓库根目录是 Obsidian Vault。项目目标很窄：用仓库内的 DeepPaperNote skill 为单篇论文生成高质量 Markdown 深读笔记，并在用户确认后同步到 GitHub。

## 运行环境

- Windows 本地脚本、测试和校验统一使用 Miniconda 环境 `deeppapernote`，不得混用裸 `python`、裸 `pip` 或其他临时 Python 环境。
- 非交互命令使用 `conda run --no-capture-output -n deeppapernote python ...` 并顺序执行，避免 Windows 下 Conda 临时文件争用和输出重新编码。
- 环境必须满足 Python `>=3.10`、可导入 PyMuPDF/`fitz` 且 `sys.flags.utf8_mode == 1`；任一条件不满足时停止并报告环境问题。

## 论文笔记工作流

1. 用户给出本地 PDF、DOI、arXiv ID、可唯一解析的标题，或 DOI／arXiv／直接 PDF URL，并要求生成论文笔记时，使用 DeepPaperNote 工作流；普通文章页 URL 应请用户改给 DOI 或 PDF，直接 PDF 无法确认可靠题名时停止。
2. 开始处理前，必须读取 `.agents/skills/DeepPaperNote/SKILL.md`，并按其中要求读取相关说明文件。
3. 每篇论文保存到 `Research/<论文标题>/笔记.md`；仅在有可靠图片时保留同级 `images/`，不得用占位文件维持空目录。
4. 任一 PDF 缺少可复核的本地文件、解析失败、实际页数不符、全文截断、逐文档 OCR 覆盖不足或关键证据缺失时停止并报告阻塞；不得生成摘要型或降级发布笔记。
5. 写入 Obsidian 前，必须验证 note plan 中各条目与 evidence ID 的关联并完成 lint。默认由主代理显式调用至少一个不同于作者的新子 agent 完成质量与可读性复核；主代理不得代写复核结果。只有用户明确选择时才改用人工复核，无法获得独立复核时停止。
6. 发布程序只接受完整证据和 `note_status: polished`，重新绑定论文类型、完整 synthesis、复核、插图来源与最终文件内容，并在同一最终事务中完成导航重建和 Vault lint。
7. 笔记完成、通过校验并保存后，必须询问用户是否需要同步到 GitHub。用户确认前不得执行 `git add`、`git commit` 或 `git push`。

## 内容与维护边界

- Zotero/infiniCloud 是可选来源。已有通道可用时优先使用可信的本地元数据和附件；不可用时继续使用本地 PDF、DOI、arXiv、可唯一解析的标题或直接 PDF URL。本仓库不自动安装 Zotero 集成。
- 临时集成状态、图片筛选过程和质量检查过程不得写入永久论文笔记；读者可见内容只保留可靠证据、真实图片和自然图注。
- 不要恢复旧 Zotero 导入脚本、旧静态索引脚本或旧 `note/` 目录工作流。
- 普通论文生成任务不得修改 `README.md` 或 `更新报告.md`。
- `README.md` 只保留稳定的用户使用说明，不记录单次更新、统计结果或内部实现细节。
- 项目维护完成后，只能在 `更新报告.md` 顶部新增一条带日期的记录；不得重写、覆盖或删除历史记录。

## 本地写入与临时授权

- 默认使用工作区写入权限：`Research/` 和其他普通项目文件可按工作流直接写入；`.agents/`、`.git/` 与 `.codex/` 保持受保护状态。
- 项目维护确需修改 `.agents/skills/DeepPaperNote/` 时，主代理必须先在现有权限内完成检查并整理完整改动，再主动向用户申请一次仅限本次维护批次和该子目录的临时写入批准。用户明确同意前不得写入。
- 已知修改应合并为一次申请和一次批量写入；若目标路径或修改范围发生变化，必须重新说明范围并申请批准。
- 不得为了绕过 `.agents/` 保护而授予永久 ACL、启用全局写入 profile、开放整个 `.agents/`，或增加权限维护脚本。写入完成后必须检查差异和 Git 状态，确认没有权限配置或临时文件进入项目。

## Git 同步边界

允许同步：

- `AGENTS.md`
- `README.md`
- `更新报告.md`
- `.gitignore`
- `.gitattributes`
- `.agents/skills/DeepPaperNote/`
- `.github/workflows/deeppapernote-v2.yml`
- `Research/*.base`
- `Research/**/*.md`
- `Research/**/images/` 下的常见图片文件

禁止同步：

- Zotero 数据库、storage、PDF、EPUB 和全文缓存
- `.local/`
- `.env`、密钥、证书和本机配置
- Obsidian workspace 状态，如 `.obsidian/`
- 临时输出、Python/Node 缓存和构建生成文件

## 同步流程

仅在用户确认后执行：

```powershell
git pull --ff-only
git status --short --ignored
git add -- AGENTS.md README.md 更新报告.md .gitignore .gitattributes .agents/skills/DeepPaperNote .github/workflows/deeppapernote-v2.yml Research
git diff --cached --check
git status --short
git commit -m "Update DeepPaperNote vault"
git push
```

提交前必须检查暂存内容，确认没有 PDF、密钥、本机配置或临时文件进入 Git。

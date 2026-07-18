# Codex + Obsidian + DeepPaperNote Vault Guide

本仓库根目录是 Obsidian Vault。项目目标很窄：用仓库内的 DeepPaperNote skill 为单篇论文生成高质量 Markdown 深读笔记，并在用户确认后同步到 GitHub。

## 论文笔记工作流

1. 用户给出论文标题、DOI、arXiv ID、URL 或本地 PDF，并要求生成论文笔记时，使用 DeepPaperNote 工作流。
2. 开始处理前，必须读取 `.agents/skills/DeepPaperNote/SKILL.md`，并按其中要求读取相关说明文件。
3. 每篇论文保存到 `Research/<论文标题>/`，目录内至少包含 `笔记.md` 和 `images/`；即使没有可靠图片，也要创建 `images/`。
4. 任一 PDF 解析失败、全文截断、OCR 覆盖不足或关键证据缺失时停止并报告阻塞；不得生成摘要型或降级发布笔记。
5. 写入 Obsidian 前，必须验证 note plan 的 evidence ID 绑定，完成 lint，并由不同于作者的另一代理或人工完成质量与可读性复核。
6. 发布器只接受完整证据和 `note_status: polished`，并核对推导出的证据与插图状态。
7. 笔记完成、通过校验并保存后，必须询问用户是否需要同步到 GitHub。用户确认前不得执行 `git add`、`git commit` 或 `git push`。

## 内容与维护边界

- Zotero/infiniCloud 是可选来源。已有通道可用时优先使用可信的本地元数据和附件；不可用时继续使用本地 PDF、DOI、arXiv 或 URL。本仓库不自动安装 Zotero 集成。
- 临时集成状态、图片筛选过程和质量检查过程不得写入永久论文笔记；读者可见内容只保留可靠证据、真实图片和自然图注。
- 不要恢复旧 Zotero 导入脚本、旧静态索引脚本或旧 `note/` 目录工作流。
- 普通论文生成任务不得修改 `README.md` 或 `更新报告.md`。
- `README.md` 只保留稳定的用户使用说明，不记录单次更新、统计结果或内部实现细节。
- 项目维护完成后，只能在 `更新报告.md` 顶部新增一条带日期的记录；不得重写、覆盖或删除历史记录。

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
- 临时输出、Python/Node 缓存和构建产物

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

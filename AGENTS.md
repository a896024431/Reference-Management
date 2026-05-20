# Codex + Obsidian + DeepPaperNote Vault Guide

本仓库的根目录就是 Obsidian Vault 根目录。当前目标很窄：用 Codex 调用仓库内的 DeepPaperNote skill，为单篇论文生成高质量 Obsidian Markdown 深读笔记。

## 默认工作方式

1. 用户给出论文标题、DOI、arXiv ID、URL 或本地 PDF，并要求生成论文笔记时，优先按 DeepPaperNote 工作流处理。
2. DeepPaperNote 是 repo-local skill，路径固定为：
   - `.agents/skills/DeepPaperNote/SKILL.md`
3. Codex 处理论文笔记任务前，必须先读取上面的 `SKILL.md`，并按其中要求读取相关 `references/` 文件。
4. 输出目录采用当前 vault 的扁平论文结构：
   - `Research/<论文标题>/`
5. 每篇论文使用独立文件夹，文件夹内至少包含：
   - `笔记.md`
   - `images/` 目录，即使暂时没有可确认图片也要创建

## DeepPaperNote 执行边界

1. 目前暂不配置 Zotero 联动，也不安装 Zotero MCP。
2. 若当前 Codex 会话没有 Zotero 工具，记录为 `Zotero not available`，然后继续使用 PDF、DOI、arXiv、URL 或开放元数据来源。
3. 不要恢复旧 Zotero 导入脚本、旧静态索引脚本或旧 `note/` 目录工作流。
4. 如果 PDF 或全文证据不足，不要把结果说成完整深读笔记；应明确标记为证据不足或降级草稿。
5. 写入 Obsidian 前按 DeepPaperNote 要求运行 lint 和最终可读性检查。
6. 运行 DeepPaperNote 脚本时，优先使用已验证的系统 Python：
   - `C:\Users\chen\AppData\Local\Programs\Python\Python311\python.exe`
   - 该解释器为 Python 3.11.5，已安装 `PyMuPDF/fitz`
   - 当前 shell 默认的 MSYS2 Python 3.12 不含 `fitz`，不适合作为 PDF 处理默认解释器

## Git 同步边界

允许同步：

- `AGENTS.md`
- `README.md`
- `.gitignore`
- `.gitattributes`
- `.agents/skills/DeepPaperNote/`
- `Research/**/*.md`
- `Research/**/images/` 下的常见图片文件

禁止同步：

- Zotero 数据库、storage、PDF、EPUB 和全文缓存
- `.local/`
- `.env`、密钥、证书和本机配置
- Obsidian workspace 状态，如 `.obsidian/`
- 临时输出、Python/Node 缓存和构建产物

## 常用同步流程

```powershell
git pull
git status --short
git add AGENTS.md README.md .gitignore .gitattributes .agents Research
git commit -m "Update DeepPaperNote vault"
git push
```

同步前先检查 `git status --short --ignored`，确认没有 PDF、密钥、本机配置或临时构建目录进入 Git。

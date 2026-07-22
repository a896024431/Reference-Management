# Codex + Obsidian + Zotero PDF Sync Vault Guide

本仓库根目录是 Obsidian Vault。项目目标很窄：按用户请求将 Zotero 当前状态手动镜像到 Vault，或为一篇已镜像的本地论文生成高质量 Markdown 深读笔记；最后由用户在 Codex 侧边栏手动同步到 GitHub。

## 运行环境

- Windows 本地脚本、测试和校验统一使用 Miniconda 环境 `deeppapernote`，不得混用裸 `python`、裸 `pip` 或其他临时 Python 环境。
- 非交互命令使用 `conda run --no-capture-output -n deeppapernote python ...` 并顺序执行，避免 Windows 下 Conda 临时文件争用和输出重新编码。
- 环境必须满足 Python `>=3.10`、可导入 PyMuPDF/`fitz` 且 `sys.flags.utf8_mode == 1`；任一条件不满足时停止并报告环境问题。

## 三类工作流

每次任务先确定属于以下哪一类。除非用户明确要求组合操作，不得因为其中一类自动启动另一类。

1. **做笔记**：仅当用户明确指定 `文献/` 内的一篇本地主文 PDF 要新建或修改笔记时，读取 `.agents/skills/DeepPaperNote/SKILL.md` 并只处理该篇论文及同目录 SI。此时才执行证据、lint、复核、图表和发布流程；PDF 解析失败或证据不足时停止。笔记输出固定为同目录的 `笔记.md` 与可选 `images/`，发布器绝不改动 PDF。
2. **同步 Zotero**：仅当用户主动要求同步文献库、分类或单篇论文时，读取 `.agents/skills/zotero-pdf-sync/SKILL.md`。该 skill 只从 Zotero `我的文库 / ZJU / 课题组` 的只读 Local API 将当前状态镜像到 `文献/`，不读写 SQLite、不使用云端 key、不部署监听。题名或分类变化时，移动整篇受管理目录（含 PDF/SI、`笔记.md` 与 `images/`），但不解析、lint、复核或改写笔记。仅整库同步中，已管理条目若从该根范围消失，就整体移至 `文献/Zotero已删除/`，随后不再由同步器管理或自动恢复；归档树不进入导航、Base 或 Git。同步索引和报告只写入 `.local/zotero-pdf-sync/`。
3. **修改项目**：README、说明、CI、skill、`.agents/` 或脚本的维护只处理改动本身。不得读取、重做、lint、复核或发布任何已有笔记，除非用户同时明确点名要求修改该篇笔记。

已完成笔记默认冻结。目录迁移、链接调整、Zotero 同步和项目维护都不构成重新精读或重新发布的理由；只有用户明确要求修改某篇笔记时才处理它。

笔记完成、通过校验并保存后，只提醒用户在 Codex 侧边栏手动同步到 GitHub。Codex 不执行 `git add`、`git commit` 或 `git push`。

## 内容与维护边界

- Zotero 是当前状态的本地镜像来源，而不是 DeepPaperNote 的运行时元数据来源。只有 `zotero-pdf-sync` 可以调用 Local API；DeepPaperNote 只接受 `文献/` 中的本地 PDF/SI，不提供联网输入、下载或元数据查询入口。其 run 与待发布 staging 固定在 `.local/deeppapernote/runs/<run_id>/` 内。
- `文献/Zotero已删除/` 是本地终态归档，不是同步目标或 DeepPaperNote 输入；不得把其中内容加入导航、Base 或 Git，也不得由同步器自动恢复。
- 临时同步状态、图片筛选过程和质量检查过程不得写入永久论文笔记；读者可见内容只保留可靠证据、真实图片和自然图注。
- 不要恢复旧 Zotero 导入脚本、旧静态索引脚本或旧 `note/`、`Research/` 目录工作流。
- 普通论文生成或同步任务不得修改 `README.md` 或 `更新报告.md`。
- `README.md` 只保留稳定的用户使用说明，不记录单次更新、统计结果或内部实现细节。
- 只有改变用户操作、数据格式、正式工作流或同步边界的项目维护，才在 `更新报告.md` 顶部新增一条带日期的记录；纯审计、注释或格式调整不记录。不得重写、覆盖或删除历史记录。

## 本地写入与临时授权

- 默认使用工作区写入权限：`文献/` 和其他普通项目文件可按工作流直接写入；`.agents/`、`.git/` 与 `.codex/` 保持受保护状态。
- 项目维护确需修改 `.agents/skills/DeepPaperNote/` 或 `.agents/skills/zotero-pdf-sync/` 时，主代理必须先在现有权限内完成检查并整理完整改动，再主动向用户申请一次仅限本次维护批次和这些明确子目录的临时写入批准。用户明确同意前不得写入。
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
- `.agents/skills/zotero-pdf-sync/`
- `.github/workflows/deeppapernote-v2.yml`
- `文献/论文导航.md`
- `文献/论文库.base`
- `文献/**/<论文标题>/笔记.md`（不含 `Zotero已删除/`）
- `文献/**/<论文标题>/images/` 下的常见图片文件（不含 `Zotero已删除/`）

禁止同步：

- Zotero 数据库、storage、PDF、EPUB 和全文缓存
- `.local/`
- `文献/Zotero已删除/`
- `.env`、密钥、证书和本机配置
- Obsidian workspace 状态，如 `.obsidian/`
- 临时输出、Python/Node 缓存和构建生成文件

## 验证范围

- 只改根目录说明、`.gitignore`、CI、`AGENTS.md` 或 skill 文档：检查相关内容，并执行 `git diff --check` 和 Git 状态检查；不运行 PDF、笔记或 skill 测试。
- 手动同步 Zotero：检查同步报告和受影响目录；整库同步还检查归档记录。不得因目录移动或归档而重新精读、lint、复核或发布笔记。只有修改同步 skill 的代码或测试时，才运行该 skill 的 Ruff 和完整 pytest。
- 修改 DeepPaperNote 的代码或测试：运行 DeepPaperNote 自身的 Ruff 和完整 pytest；只有改动导航/Vault 契约或正式笔记输出时，才额外运行导航检查和 Vault lint。除非用户明确指定，不读取已有笔记或 PDF。
- 明确新建或修改某篇笔记：仅对该篇执行 DeepPaperNote 的正式流程和所需复核；发布时重建导航并运行 Vault lint。
- 只有改动两个 skill 的共享契约或 CI 时，才运行两个 skill 的完整测试。

## 用户手动同步

Codex 按上述范围完成检查后，不暂存、不提交、不推送。

每次任务按以下顺序执行：

1. 用户先 Pull，使本地仓库与 GitHub 同步。
2. Codex 修改文件并完成相应检查。
3. 用户检查改动，只暂存上述允许同步的文件。
4. Commit，建议提交信息为 `Update DeepPaperNote vault`。
5. Push。

提交前必须确认没有 PDF、密钥、本机配置或临时文件进入暂存区。

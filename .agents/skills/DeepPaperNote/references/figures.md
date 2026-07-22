# 图表

## 读者内容与本地记录

figure manifest、decisions、contact sheet 与视觉复核都属于当前 run 的本地处理记录。永久笔记只面向读者，只能出现真实图片、原始 Fig./Table 编号和自然图注。

不得把可见 placeholder、候选 ID、裁剪坐标、内容指纹、建议位置、QA 术语或隐藏 figure 注释写进 `文献/`。

## 简单的内部流程

1. 从当前主文/SI 提取候选；每个候选都只有当前 run 的固定 manifest 文件名。
2. 写正文时，作者只决定是否嵌入该文件名，例如 `![[images/fig-...png|420]]`；不编辑 decisions JSON。
3. `plan_figures_v2.py --finalize-note` 从正文实际引用的文件名生成最终选择。名称必须在当前 manifest 中唯一存在；未知、拼错或旧 run 名称立即失败。
4. 已引用的候选为 `inserted`，未引用的候选为 `omitted`。新流程不产生 placeholder。
5. 只对 `inserted` 图片建立 contact sheet 并做轻量视觉复核；没有插图时这两步不运行。
6. 发布器从当前 manifest 复制已选图片，并核对正文引用、最终选择、`images/` 内容和哈希完全相同。

拒绝 caption-only、正文主导页面、缺失表体、不可读坐标、混入其他 caption 的图片，以及会误导的局部复合图。图号匹配本身不足以插入。

证据提取没有识别 caption、但 manifest 中存在 `anchored_label_v2` 且质量为 usable 的资产时，`plan_figures_v2.py` 可建立 bridge intent；仍只允许正文实际引用其中的当前文件名。

## 发布格式与状态

可靠图片放在支持它的段落后：

    ![[images/fig-doc-example-p0003-fig-2.png|420]]
    *Fig. 2｜器件几何与测量回路。它解释两个边缘通道为何可分别调节。*

保留原始 Fig. X、Table X、Fig. Sx 或 Extended Data Fig. X，不按笔记顺序重编号。图注解释科学价值，不解释提取过程。

没有实际插图时，frontmatter 为 `figure_status: none_needed`；有插图时为 `complete`。旧笔记的 `placeholder_only` 与 `partial` 仅保留兼容性，不是新流程输出。

远程、data URI、HTML 图片、未被笔记引用的图片和指向不存在图片的链接都会阻止发布。`images/` 中的非图片文件或子目录同样阻止发布。

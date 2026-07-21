# Figure Decisions

## 两个受众

figure manifest、decisions、contact sheet 与视觉复核属于本地处理记录。永久笔记只面向读者，只能出现通过来源与可用性强制检查的真实图片、原始 Fig./Table 编号和自然图注。

不得把可见 placeholder、候选 ID、裁剪坐标、内容指纹、建议位置、QA 术语或隐藏 figure 注释写进 `文献/`。

## 决策流程

1. 先确定视觉对科学论证的作用。
2. 用原始 caption、附近正文、页码和 document ID 确认身份。
3. 独立检查主体完整、轴与图例可读、表体存在、复合图无误导性裁断。
4. 记录 `inserted`、`placeholder` 或 `omitted`、目标章节和原因。
5. 只有语义与视觉复核都通过时才插入。

拒绝 caption-only、正文主导页面、缺失表体、不可读坐标、混入其他 caption 的图片，以及会误导的局部复合图。图号匹配本身不足以插入。

证据提取没有识别 caption、但 manifest 中存在 `anchored_label_v2` 且质量为 usable 的资产时，`plan_figures_v2.py` 可建立 bridge intent；必须保留 document ID、原始标签和来源页。

## 发布格式与状态

可靠图片放在支持它的段落后：

    ![[images/fig-doc-example-p0003-fig-2.png|420]]
    *Fig. 2｜器件几何与测量回路。它解释两个边缘通道为何可分别调节。*

保留原始 Fig. X、Table X、Fig. Sx 或 Extended Data Fig. X，不按笔记顺序重编号。图注解释科学价值，不解释提取过程。

placeholder 与 omitted 只留在 JSON。没有需要决策的重要视觉时 decisions 可为空，frontmatter 为 `figure_status: none_needed`。发布程序按 decisions 自动推导并核对 `none_needed`、`placeholder_only`、`partial` 或 `complete`。

## 视觉复核与内容指纹

`build_figure_contact_sheet_v2.py` 只使用 manifest 候选，完整写好 PNG 后再替换旧文件；`record_figure_visual_review_v2.py` 记录 manifest、decisions 与 contact sheet 之间的对应关系。

插入的图片必须绑定当前 paper record 中存在的 document/page，稳定身份、contact sheet decisions、视觉复核和文件内容指纹都必须匹配，并且在笔记中有对应的 `images/<文件名>` embed。远程、data URI、HTML 图片、未被笔记引用的图片和指向不存在图片的链接都会阻止发布。`images/` 中的非图片文件或子目录同样阻止发布。

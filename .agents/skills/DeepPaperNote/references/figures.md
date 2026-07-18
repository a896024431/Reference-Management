# Figure Decisions

## 两个受众

figure_manifest.json、figure_decisions.json、contact sheet 和视觉复核属于运行审计。Research/<标题>/笔记.md 只面向读者。

永久笔记只能出现通过身份与可用性门禁的真实图片、原始 Fig./Table 编号和自然图注。不得出现可见 placeholder、候选 ID、裁剪坐标、哈希、建议位置、放置原因、当前状态、QA 术语或隐藏 figure 注释。

## 决策流程

对每个重要视觉先确定科学作用，再查看候选：

1. 优先实验或理论设置、主要观测、关键定量结果和能消除误读的比较。
2. 使用原始 caption、附近正文、页码和 document_id 确认身份。
3. 独立检查视觉可用性：主体完整、轴与图例可读、表格正文存在、复合图不会被截断误导。
4. 记录 inserted、placeholder 或 omitted，以及目标章节和原因。
5. 只有模型完成语义确认后才能从 placeholder 改为 inserted。

拒绝 caption-only 裁剪、正文占主导的页面、缺失表体、无法辨认坐标的图、被其他 caption 污染的裁剪和会误导的局部复合图。图号匹配本身不足以插入。

## Manifest-caption bridge

当证据提取没有识别 caption，但 canonical manifest 存在 anchored_label_v2 且 visual_quality_status 为 usable 的资产时，plan_figures_v2.py 可以建立 bridge intent。

Bridge 必须保持 document_id、原始标签和来源页，不得把主文与补充材料的同号图合并，也不得从普通正文引用或 reject 资产创建目标。

## 发布格式

可靠图片放在支持它的分析段落之后，例如：

    ![[images/fig-doc-example-p0003-fig-2.png|420]]
    *Fig. 2｜器件几何与测量回路。它说明了为何两个边缘通道可以分别调节。*

保留 Fig. X、Table X、Fig. Sx 或 Extended Data Fig. X，不按笔记顺序重新编号。图注解释科学阅读价值，不解释提取过程。

placeholder 或 omitted 只留在 JSON。没有可靠图片时保持正文完整，不显示道歉或占位框。

## 视觉复核与哈希

build_figure_contact_sheet_v2.py 只使用 manifest 中的候选并原子写入 PNG。record_figure_visual_review_v2.py 记录独立复核；发布器验证 visual review、contact sheet、manifest 和 decisions 的身份及哈希。

插入资产必须存在、可解码、文件哈希匹配且在笔记中恰好有对应 embed。未引用图片视为孤儿，引用不存在的图片视为坏链接，二者都阻止发布。

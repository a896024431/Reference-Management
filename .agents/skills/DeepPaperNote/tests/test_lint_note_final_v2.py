from __future__ import annotations

from lint_note import mixed_language_issues, suspicious_mid_sentence_linebreaks
from lint_note_final_v2 import visible_prose
from lint_note_release_v2 import reader_visible_figure_metadata_issues


def test_visible_prose_ignores_frontmatter_link_targets_and_inline_math() -> None:
    text = """---
title: Long English title in a local paper collection
local_pdf: 文献/9/Universal chiral Luttinger liquid behavior in graphene.pdf
---

# 中文题名

这里的 $G=\\mathrm dI/\\mathrm dV\\propto V^2$ 是微分电导。

- [[Research/A very long English paper title/笔记|相关中文笔记]]：用于比较。
"""
    prose = visible_prose(text)
    assert "local_pdf" not in prose
    assert "A very long English paper title" not in prose
    assert "相关中文笔记" in prose
    assert not mixed_language_issues(prose)


def test_visible_prose_ignores_multiline_display_math_for_linebreak_gate() -> None:
    text = """---
title: Paper
---

上一段完整结束。

$$
G(V,T)=A
\\qquad
T^2.
$$

下一段完整结束。
"""
    prose = visible_prose(text)
    assert "\\qquad" not in prose
    assert not suspicious_mid_sentence_linebreaks(prose)


def test_visible_prose_still_flags_real_english_fragment_in_chinese_sentence() -> None:
    text = """---
title: Paper
---

这里突然出现 this is a badly translated and unfinished English fragment 影响阅读。
"""
    assert mixed_language_issues(visible_prose(text))


def test_reader_visible_figure_metadata_allows_natural_image_caption() -> None:
    text = """---
title: Test
---

![[images/fig-doc-abc123-p0002-fig-1-a82457a77b743b98.png]]

*Fig. 1 展示四个栅极与输运接触的相对位置；它是理解后文测量几何的参照。*

正文结合 Fig. 1 讨论器件结构，不解释图片提取或发布过程。
"""

    assert reader_visible_figure_metadata_issues(text) == []

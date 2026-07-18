from __future__ import annotations

from lint_note_v2 import (
    reader_visible_figure_metadata_issues,
    visible_linebreak_issues,
    visible_prose,
)
from note_lint_core import mixed_language_issues, suspicious_mid_sentence_linebreaks


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


def test_evidence_anchor_does_not_trigger_mixed_language_false_positive() -> None:
    text = (
        "---\ntitle: Test\n---\n"
        "湿度高于 50%，线宽约 60 nm，激励为 18 V 与 150 kHz。"
        "（主文 p. 8，Methods）\n"
    )

    prose = visible_prose(text)

    assert "Methods" not in prose
    assert mixed_language_issues(prose) == []


def test_visible_prose_excludes_preserved_manual_section() -> None:
    note = """---
type: paper
---

## 正文

这是一段需要执行语言检查的自然中文。

## 我的笔记

- 原始人工内容保留 Thomas-Fermi、crossover 与 QPC，不由迁移器润色。

## 引用

正式引用继续保留在后续章节。
"""
    prose = visible_prose(note)
    assert "自然中文" in prose
    assert "正式引用" in prose
    assert "Thomas-Fermi" not in prose
    assert "crossover" not in prose


def test_visible_prose_only_removes_manual_section_body() -> None:
    note = """## 我的笔记

user-authored English phrase

## 相关论文

这里的正文仍要接受检查。
"""
    prose = visible_prose(note)
    assert "user-authored" not in prose
    assert "这里的正文" in prose


def test_consecutive_ordered_list_items_are_not_mid_sentence_breaks() -> None:
    note = """---
title: Paper
---

1. **第一项。** 这是一条完整说明。
2. **第二项。** 这也是一条完整说明。（主文 p. 2, Fig. 1）
3. **第三项。** 这仍是一条完整说明。
"""
    assert visible_linebreak_issues(visible_prose(note)) == []


def test_real_pdf_style_wrapping_remains_reported() -> None:
    note = """---
title: Paper
---

这是一句被错误截断的正文
下一行继续同一句话。
"""
    assert visible_linebreak_issues(visible_prose(note))


def test_visible_prose_removes_parenthesized_and_display_tex() -> None:
    text = (
        "---\ntitle: Test\n---\n"
        "\u4e2d\u6587 \\(g=0.47\\pm0.01\\,\\mathrm{mK}\\) \u7ed3\u8bba\u3002\n"
        "\\[R \\propto T^{-1}\\]\n"
    )

    prose = visible_prose(text)

    assert "mathrm" not in prose
    assert "propto" not in prose
    assert "中文" in prose

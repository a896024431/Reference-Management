from __future__ import annotations

from lint_note_final_v2 import visible_linebreak_issues, visible_prose


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

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lint_note_final_v2 import visible_prose  # noqa: E402


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

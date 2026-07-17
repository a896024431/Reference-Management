---
type: paper
title: "{{ title }}"
title_zh: "{{ title_zh }}"
authors: {{ authors_yaml }}
year: {{ year }}
venue: "{{ venue }}"
domain: "{{ domain }}"
topics: {{ topics_yaml }}
paper_type: "{{ paper_type }}"
evidence_level: "{{ evidence_level }}"
note_status: "{{ note_status }}"
figure_status: "{{ figure_status }}"
aliases: {{ aliases_yaml }}
tags: {{ tags_yaml }}
---

# {{ title }}

## 30 秒速览

{{ fast_summary }}

## 关键结论

- {{ claim_1 }}〔{{ evidence_anchor_1 }}〕
- {{ claim_2 }}〔{{ evidence_anchor_2 }}〕
- {{ claim_3 }}〔{{ evidence_anchor_3 }}〕

## 关键数字

- {{ key_number }}：{{ meaning_and_condition }}〔{{ evidence_anchor }}〕

## 适用边界

{{ boundary }}

## 快速入口与页面导航

- 原文：{{ local_pdf_link }}
- 补充材料：{{ supplement_links }}
- 导航：[[#原文摘要翻译]] · [[#研究问题]] · [[#主要结果与证据链]] · [[#局限与未决问题]]

## 术语与符号

- **{{ term }}**：{{ concise_definition }}

## 原文摘要翻译

> [!abstract]- 展开查看中文摘要
> {{ translated_abstract }}

## 创新点

{{ innovations }}

## 研究问题

{{ research_problem }}

## 实验体系、方法或理论模型

{{ domain_adapted_method }}

## 主要结果与证据链

{{ results_and_evidence }}

## 解释、替代解释与证据边界

{{ interpretation }}

## 局限与未决问题

{{ limitations }}

## 可复用结论

{{ reusable_takeaways }}

## 相关论文

{{ related_notes }}

## 我的笔记

{{ preserved_user_notes }}

## 引用

{{ citations }}

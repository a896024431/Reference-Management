# Figure Decisions and Reader-Facing Placement

Every high-value figure or table must be assessed, but the assessment and the published note serve different audiences.

## Two Outputs, Two Audiences

- `figure_manifest.json` and `figure_decisions.json` are run artifacts. They retain target section, candidates, rejection reasons, crop details, hashes, and visual-review evidence.
- `Research/<paper title>/笔记.md` is a reader-facing research note. It contains only an accepted image with a natural caption, or no figure block at all.

Never turn pipeline records into prose for readers. In particular, a permanent note must not contain `建议位置`, `放置原因`, `当前状态`, `[!figure]`, hidden `figure-target` comments, candidate IDs, crop coordinates, contact-sheet references, hashes, or QA language.

## What to Prefer

Prioritize visuals that materially improve understanding:

1. experimental or theoretical setup needed to interpret the paper;
2. the principal observation or quantitative result;
3. a diagram, table, or comparison that resolves a likely reader misunderstanding;
4. a supporting visual only when prose alone would be materially less clear.

Do not select a figure merely because it appears early in the paper or because extraction found an image file.

## Evidence Used for a Decision

Use the original caption, nearby discussion, page context, and deterministic PDF-asset candidates. Resolve the semantic role before judging the candidate image.

The selected image must pass two independent gates:

- **identity match**: label, caption, page, and local context match the intended figure/table;
- **visual usability**: the visible body is sufficiently complete and legible for the claim the note makes.

Reject caption-only crops, images dominated by prose, partial composite figures that would mislead on their own, figures with unreadable axes or legends when those carry the argument, and table crops without a usable table body. A matching figure number alone is never enough.

## Final-Note Format

For an accepted image, put the embed immediately after the reader-facing explanation it supports. Use the original paper label and a concise caption written as normal note prose:

```md
![[images/fig-doc-example-p0003-fig-2.png|420]]
*Fig. 2｜器件几何与测量回路。它说明了为何该实验能够分别调节两个边缘通道。*
```

Rules:

- Preserve `Fig. X`, `Table X`, `Fig. Sx`, or `Extended Data Fig. X`; do not renumber by note order.
- Explain the scientific reading value, not the extraction process.
- State that an image is a partial panel only when that fact is scientifically necessary to interpret it, not as a QA disclaimer.
- Prefer a nearby paragraph over a caption that repeats the same sentence.

## When No Image Is Published

A `placeholder` or `omitted` decision remains in `figure_decisions.json`; it is not a visible placeholder in the note. Do not write a callout, status line, or apology. Keep the relevant evidence and conclusion in prose, and let the run report record why no image was inserted.

Textual coverage is more important than image count. Do not use a low-quality crop merely to increase visual coverage.

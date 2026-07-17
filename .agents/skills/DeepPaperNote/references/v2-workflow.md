# DeepPaperNote v2 Workflow

This document defines the version-2 contract. It supplements the MVP workflow and is
normative whenever a v2 artifact is present.

## Invariants

- Every artifact has `schema_version: 2`, `paper_id`, `run_id`, `status`, and `failures`.
- `paper_id` and `run_id` must agree across all artifacts in one run.
- A paper owns one or more `documents`; the main article and supplements are not separate papers.
- Evidence retains `document_id`, document role, PDF page, section, and stable `evidence_id`.
- A complete note is published only when all reports bind to the final Markdown SHA-256.
- Temporary artifacts live under `.local/deeppapernote/runs/<run_id>/`, never in a
  Vault-searchable scratch folder.

## Artifacts

### `paper_record.json`

Required fields:
- `schema_version`, `paper_id`, `run_id`, `status`, `failures`
- `metadata`: canonical title, authors, year, venue, identifiers and source URLs
- `documents[]`: `document_id`, `role` (`main` or `supplement`), source, Vault-relative
  local path when applicable, SHA-256, and page count

### `evidence_pack.json`

Required fields:
- the common envelope
- `paper_type`
- `evidence_units[]`: `evidence_id`, `document_id`, `document_role`, `page`, `section`,
  `kind`, `text`, and any figure/table/equation references
- `coverage`: profile-specific required evidence and its status
- `quality`: `pass`, `degraded`, or `fail`, with reasons

Quality is based only on evidence applicable to the selected paper profile. A paper with no
table must not be penalized for having no table caption.

### `note_plan.json`

Required fields:
- the common envelope and paper type/domain
- `must_cover[]`, each linked to evidence IDs
- `key_claims[]`, `key_numbers[]`, `section_plan[]`, and `figure_intents[]`

### Figure artifacts

`figure_manifest.json` records collision-proof candidates with source document, page,
caption/crop identity, SHA-256, and visual-quality signals.

`figure_decisions.json` records one final decision per important visual:
`inserted`, `placeholder`, or `omitted`, plus target section and reason.

These are run artifacts, not note content. A permanent note shows an accepted image only as a direct embed with natural reader-facing prose. `placeholder` and `omitted` decisions, candidate IDs, crop details, hashes, rejection reasons, contact-sheet references, and QA status must never be rendered into `笔记.md`.

### Review artifacts

- `lint_report.json`: deterministic note/vault checks and note SHA-256
- `quality_review.json`: evidence fidelity, completeness, domain fit and traceability
- `readability_review.json`: Chinese naturalness and navigation review

Each review uses the final note hash. Any edit invalidates earlier reviews and requires reruns.

## Paper Profiles

Supported primary types:
- `experimental_physics`
- `theoretical_physics`
- `materials_fabrication`
- `AI_method`
- `benchmark_or_dataset`
- `clinical_or_psychology_empirical`
- `humanities_or_social_science`
- `survey`
- `generic`

The fallback is `generic`; never default to `AI_method`.

Experimental-physics notes use the chain:
`system/control -> direct observable -> analysis/calibration -> physical inference -> alternatives`.
They must not be forced into an AI-style input/output narrative.

## One-File, Two-Layer Note

Every paper remains `Research/<canonical title>/笔记.md`.

Fast layer:
1. `30 秒速览`
2. `关键结论`
3. `关键数字` when applicable
4. `适用边界`
5. `快速入口与页面导航`
6. an optional compact glossary

Deep layer:
1. translated abstract
2. paper-specific innovations
3. research problem
4. domain-adapted experiment/method/derivation
5. results and evidence chain
6. physical or conceptual interpretation and alternatives
7. limitations and open questions
8. reusable conclusions, related papers, and citations

Central claims must point to a stable source such as `主文 p. 4, Fig. 2` or
`补充材料 p. 7, Eq. S3`.

## Publish Gate

The publisher stages a complete paper directory, validates it, and atomically replaces the
formal directory only after all gates pass. A failed run leaves the prior note untouched.

Normal publication requires:
- evidence quality `pass`
- no unresolved unsupported central claim
- all five review dimensions at least 4/5
- all important figures decided
- every inserted asset present, decodable, and hash-matched
- no absolute machine path, runtime integration message, broken link/embed, orphan image, reader-visible figure-planning metadata, or hidden figure-target comment

A degraded publication must say why it is degraded in both frontmatter and the first screen.

## Zotero

Zotero is an optional provider. Probe it at runtime and prefer a confident local-library hit,
but never write availability messages into the permanent note. Store capability status only
in the run manifest and fall back to local PDFs and stable identifiers when needed.


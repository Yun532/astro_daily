# Astro Daily Feedback and Quality Plan

## Goals

Turn Astro Daily from a strong rule-and-prompt based recommender into a personal literature assistant that learns from feedback and checks its own explanations before publishing.

The plan has two tracks:

1. Feedback loop: learn what the reader actually values.
2. Content quality gate: keep explanations grounded, detailed, readable, and useful.

## Track 1: Feedback Loop

### Phase 1: Feedback File

Add a lightweight append-only `feedback.jsonl` file. Each line records one judgment:

```json
{"date":"2026-05-13","paper_id":"2605.11894","rating":"love","reason":"cluster neutrino/gamma-ray connection is very relevant"}
{"date":"2026-05-13","paper_id":"2605.11085","rating":"skip","reason":"too far from high-energy astrophysics"}
```

Supported ratings:

- `love`: very relevant; boost similar papers.
- `useful`: relevant and worth reading.
- `skip`: not interesting enough.
- `bad`: recommendation quality was poor or off-topic.

### Phase 2: Feedback Ingestion

Add a small module, likely `astro_daily/feedback.py`, that:

- loads recent feedback records,
- validates paper ids and ratings,
- summarizes positive and negative patterns,
- exposes a compact payload for LLM scoring.

The scoring prompt should receive only recent, compact feedback, not the entire history.

### Phase 3: Local Scoring Adjustments

Before or after LLM scoring, apply small local adjustments:

- boost terms and categories repeatedly marked `love` or `useful`,
- downweight terms repeatedly marked `skip` or `bad`,
- prevent one disliked subtopic from dominating the report,
- preserve strong hard-result papers even when they do not match exact keywords.

### Phase 4: WeChat/CLI Feedback Commands

Add simple commands first:

```powershell
python -m astro_daily feedback love 2605.11894 --reason "cluster neutrino/gamma-ray"
python -m astro_daily feedback skip 2605.11085 --reason "too cosmology-heavy"
```

Later, allow WeChat replies such as:

```text
love 2605.11894 cluster neutrino/gamma-ray
skip 2605.11085 too far from my interests
```

## Track 2: Content Quality Gate

### Phase 1: Quality Schema

After summaries are generated, run a structured quality check per selected paper:

```json
{
  "paper_id": "2605.11894",
  "grounding_score": 8,
  "depth_score": 9,
  "clarity_score": 8,
  "formula_quality": 8,
  "figure_quality": 7,
  "personal_relevance_score": 9,
  "repair_needed": true,
  "issues": ["model_fitting_cn is too generic"],
  "repair_instruction": "Add this paper's actual fitted quantities, degeneracies, and observational diagnostics."
}
```

### Phase 2: Repair, Not Delete

Quality checking must not make reports shorter or more conservative in the wrong way. The rule is:

- Do not invent links, figure URLs, DOI values, or paper-specific claims.
- Do explain background, physical pictures, standard derivations, model fitting, and figure-reading logic in detail.
- If a section is generic, repair that section only.
- If a paper-specific fact is uncertain, say what should be checked in the paper rather than fabricating it.

### Phase 3: Minimum Content Contract

Each selected paper should keep:

- a concise summary,
- why it matters,
- why it matches the reader's interests,
- detailed explanation,
- background,
- basic theory,
- formula derivation,
- model fitting,
- key sections,
- figure-reading guidance,
- related work guidance.

Quality gate should fail or repair a summary if it becomes too short, too vague, or too hard to follow.

### Phase 4: Publish Safety

The report should still be generated when quality checking fails. Failure modes:

- If quality check fails for one paper, keep the summary and log a warning.
- If summary generation fails for one paper, use a clearly marked fallback summary from title/abstract.
- If all summaries fail, still write a minimal report with selected papers and reasons, but do not mark them seen unless push/publish succeeds.

## Immediate Reliability Fix

Today, 2026-05-13, the run failed after paper selection because the LLM summary returned malformed JSON with LaTeX backslashes. The immediate fix is:

- improve JSON repair for LaTeX escapes,
- split summary batches recursively,
- when a single-paper summary still fails, attach a safe fallback summary and continue report generation.

This keeps the daily report from failing completely because one summary response is malformed.

## Implementation Status

- Done: lightweight `feedback.jsonl` storage and CLI feedback commands.
- Done: recent feedback is compacted and passed into LLM scoring as a soft preference signal.
- Done: local content quality checks run after summaries and are written into the pipeline log.
- Done: malformed JSON repair, single-paper fallback summaries, parallel per-paper summaries, and parallel figure selection.
- Next: add an optional LLM repair step for summaries that fail the local content quality check.

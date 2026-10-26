# Product Roadmap

> **Type:** Roadmap | **Must stay current:** Yes -- update when phases, features, or priorities change

<!-- AI Context
Role: This is the top-level sequencing document for the entire product.
It defines development phases, maps PRDs to phases, and captures the
rationale for ordering. Use it to understand *what is being built when*
and *why that order was chosen*.

When a new PRD is created, register it here under the appropriate phase.
When a feature ships or a phase graduates, update the status columns.
When priorities shift, update phase assignments and record the reasoning
in the Prioritization Log below.

Individual PRDs hold feature-level detail. This document holds the
cross-feature ordering logic. Do not duplicate PRD content here.
-->

## Product Vision

A Document Intelligence Agent that turns an uploaded invoice or receipt into validated,
structured data and a trustworthy AI summary — built with production-style engineering
(tests, CI, Docker, observability, guardrails) and AI agents that call real tools.

## Phasing Strategy

Phases follow the assessment brief's dependency chain: foundation first, then the five
core parts in dependency order (the validation tool before the agent that calls it), then
the UI, then the bonus tasks, then a submission pass. A phase graduates when every PRD in
it is `shipped` (acceptance criteria met, CI green, merged into `dev`).

Module numbers are assigned only when a feature starts. Rows marked *planned* have no
PRD yet; their numbers are expectations from the local feature map.

## Phases

### Phase 0: Foundation

**Trigger:** Project kickoff.
**Graduation criteria:** `docker compose up --build` starts db + backend + frontend; CI green; migrations enable pgvector.

| PRD | Module | Status | Notes |
|---|---|---|---|
| `docs/prd/0000-setup-prd.md` | `backend/app/core/`, `frontend/`, `db/`, CI | shipped | Reserved number 0000; CI run #1 green (2026-10-26) |

### Phase 1: Core Pipeline (brief Parts 1–5)

**Trigger:** Phase 0 shipped.
**Graduation criteria:** Uploading a sample invoice returns `{document_id, structured_data, validation, summary}` end to end, with validation run before the summary.

| PRD | Module | Status | Notes |
|---|---|---|---|
| `docs/prd/0001-documents-prd.md` | `modules/documents` | shipped | Part 1 — upload API; CI run #4 green (2026-10-26) |
| `docs/prd/0002-text-extraction-prd.md` | `modules/text_extraction` | shipped | Part 2 — PDF parser + OpenAI vision; CI run #7 green (2026-10-26) |
| `docs/prd/0003-structured-extraction-prd.md` | `modules/structured_extraction` | shipped | Part 3 — structured outputs; CI run #10 green (2026-10-26) |
| `docs/prd/0004-validation-prd.md` | `modules/validation` | shipped | Part 5 — deterministic checks + static-rate conversion; CI run #13 green (2026-10-26) |
| `docs/prd/0005-agent-prd.md` | `modules/agent` | shipped | Part 4 — Document Agent + AgentRunner; end-to-end upload → result; CI run #16 green (2026-10-27) |

### Phase 2: User Interface

**Trigger:** 0005 API contract stable.
**Graduation criteria:** Upload, status, and results (data, validation, summary) usable in the browser.

| PRD | Module | Status | Notes |
|---|---|---|---|
| `docs/prd/0006-frontend-prd.md` | `frontend/` | shipped | Upload, documents list, document detail + multi-agent view; CI run #20 green (2026-10-27) |

### Phase 3: Bonus Tasks

**Trigger:** Phase 1 shipped (Phase 2 may run alongside).
**Graduation criteria:** All five bonus tasks shipped; `AGENT_MODE=multi` is the default.

| PRD | Module | Status | Notes |
|---|---|---|---|
| *planned* 0007 | `modules/observability` | planned | B1 — first, so later features get traces/tokens |
| *planned* 0008 | `modules/guardrails` | planned | B2 — grounding, confidence, retry |
| *planned* 0009 | `modules/vision` | planned | B5 — tables, layout, multimodal |
| *planned* 0010 | `modules/retrieval` + Query Agent | planned | B3 — pgvector |
| *planned* 0011 | `modules/agent` (multi-agent) | planned | B4 — last, reuses every tool |

### Phase 4: Submission

**Trigger:** Phases 1–3 shipped.
**Graduation criteria:** README setup works from a clean clone; ENGINEERING_NOTES covers architecture, prompt design, limitations, production improvements; repo public.

| PRD | Module | Status | Notes |
|---|---|---|---|
| — | `README.md`, `ENGINEERING_NOTES.md` | planned | Docs pass; may not need its own PRD |

## Cross-Cutting Concerns

| Concern | Introduced In | Matured In | Current State |
|---|---|---|---|
| Docker Compose (full stack) | 0000 | 0006 | db + backend + frontend run with one command |
| CI (GitHub Actions) | 0000 | each feature | backend + frontend jobs green |
| LLM client (tokens, fakes, retries) | 0000 | 0007, 0008 | client seam + FakeLLM + token capture |
| Persistence (Postgres + pgvector, Alembic) | 0000 | 0010 | Postgres 18, pgvector enabled by baseline migration |
| Observability | 0000 (logging) | 0007 | JSON logging + `document_id` context var |
| ENGINEERING_NOTES.md | 0000 (stub) | every feature | stub with architecture decisions |

## PRD Registry

| PRD | Phase | Module | Status |
|---|---|---|---|
| `docs/prd/0000-setup-prd.md` | 0 | foundation | shipped |
| `docs/prd/0001-documents-prd.md` | 1 | documents | shipped |
| `docs/prd/0002-text-extraction-prd.md` | 1 | text_extraction | shipped |
| `docs/prd/0003-structured-extraction-prd.md` | 1 | structured_extraction | shipped |
| `docs/prd/0004-validation-prd.md` | 1 | validation | shipped |
| `docs/prd/0005-agent-prd.md` | 1 | agent | shipped |
| `docs/prd/0006-frontend-prd.md` | 2 | frontend | shipped |

## Prioritization Log

| Date | Change | Reason |
|---|---|---|
| 2026-10-26 | Validation (brief Part 5) ordered before the agent (Part 4) | The agent must call the validation tool before summarizing |
| 2026-10-26 | Observability first among bonus tasks; multi-agent last | Observability benefits every later feature; multi-agent reuses all tools |
| 2026-10-26 | SQLite replaced by Postgres 18 + pgvector in Docker | User preference; also serves the RAG bonus without a separate vector store |

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/documentation-standard.md` | Standard | Governs how all docs are maintained |
| `docs/reference/folder-structure.md` | Reference | Structural placement of modules |
| `docs/decisions/NNNN-*.md` | Decision log | Deviations that may affect roadmap |
| `docs/prd/source/feature-map.md` | Local guideline (gitignored) | Build order and dependencies from the brief |

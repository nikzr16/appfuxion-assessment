# 0011 - Retrieval implementation details that differ from the 0010 PRD and plan

> **Date:** 2026-10-27 | **Status:** Accepted

<!-- AI Context
Role: This is an append-only record of a single implementation divergence.
Each entry captures why the deviation happened and what it affects.
Never edit an existing decision log entry. To reverse a previous decision,
create a new entry that references the original. After adding an entry,
check the impact checklist below and update affected workflow or reference
docs before the session ends.
-->

## Context

Implementing `docs/plan/0010-retrieval-plan.md`, running the back-fill and the Document Agent
on the development data with the real OpenAI API, asking the Query Agent questions and
checking the UI in the browser (desktop and 375 px, light and dark) changed a few details.
None changes the PRD's decisions D1–D14, the stored tables or the API shapes it lists.

## Decision

1. **`AgentRunner` gained an optional `tool_choice`.** PRD D8's rationale said the runner
   "stays unchanged". The plan already announced this addition: the Query Agent passes
   `tool_choice="required"` (through `LLMClient.complete`) so a model cannot end a turn with
   plain text, which the runner reports as `agent_incomplete`. The default is `None`, so the
   Document Agent's calls are byte-for-byte as before.
2. **A third Query Agent route, `GET /api/query/suggestions`.** D10 lists `POST /query` and
   `GET /conversations/{id}`; D11 asks for example questions "built from real indexed vendors"
   and an empty-index state. Both need data the browser cannot get from the other routes, so a
   small read-only route returns `{indexed_documents, questions}` built by code (no LLM).
3. **The number check is reached through `retrieval.service`.** The plan put `number_tokens`
   in the pure `retrieval/rules.py` and had the Query Agent use it. Importing another module's
   non-service file breaks the layering rule (service / schema only), so `retrieval.service`
   exposes `number_tokens` and `unverified_numbers` as thin wrappers; a layering test now
   checks that no other module imports `retrieval.rules`, `crud` or `model`.
4. **`FakeLLM.embed_error`.** Besides the planned `embedder` hook, the fake gets an
   `embed_error` attribute (raised by the next `embed` call) so the "embedding failed, the run
   still completes" paths are tested through the real call path and ledger.
5. **No per-code issue labels in the UI.** The plan listed `lib/issues.ts` labels for the
   three new codes. The Issues list shows each issue's message and field (never the code), so
   the new issues needed no label; only friendly error texts for `query_failed` and the
   transient `llm_*` codes were added to `lib/errors.ts`.
6. **Front-end bundle split.** The new UI pushed the main chunk from 487 kB to 513 kB, over
   Vite's 500 kB warning. The chat panel is loaded on first open (`React.lazy`) and React /
   React Router / TanStack Query go into their own vendor chunks (`manualChunks`); the main
   chunk is now 361 kB and nothing behaves differently.
7. **UI details from the browser check.**
   - The Vendor history card's grid is explicitly one column on phones: the implicit column
     grew to the rows' minimum width and overflowed the card at 375 px.
   - Invoice rows (vendor history, same-number list, similar invoices) are two lines: invoice
     number or vendor on top; date, vendor or similarity below; the total on the right. One
     line squeezed the vendor down to a single letter in the narrow similar-invoices column.
   - Citations in the chat show the vendor on the first line and "number · date · total"
     below, so the invoice number is never cut off.
   - After an answer arrives the chat scrolls to the top of the newest question (not the
     bottom), so a long answer is read from its start.
   - The range bar's track uses the stronger border token; the surface token was invisible in
     dark mode.

## Reason

Each change keeps the PRD's intent (one-way dependencies, code-checked answers, the floating
chat and the vendor-history card as agreed) with less coupling, testable failure paths or a
screen that works at every width.

## Observed, not changed

Running the real data showed that four sample vendors share one SST number (the sample PDFs
come from one template). Under D4 (tax ID first) their invoices form one vendor history, and
the Query Agent then quoted CloudNine Hosting's converted total as "the highest Acme Trading
total". This is D4 working as written. It is recorded as a limitation in ENGINEERING_NOTES
(a misread buyer tax ID would do the same) and offered to the user as a follow-up (require a
similar name before a tax-ID match merges vendors); the rule was not changed here.

## Impact

- [x] Reference doc updated (`docs/reference/folder-structure.md`)
- [x] ENGINEERING_NOTES.md 0010 sections describe the shipped behaviour
- [x] README.md and CLAUDE.project.md updated (Ask AI, back-fill, `QUERY_MAX_STEPS`, agent roster)

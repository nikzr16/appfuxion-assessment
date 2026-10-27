# 0010 Retrieval PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Let every processed invoice be **compared with the invoices that came before it**. Each
completed document is indexed in Postgres with **pgvector** (one embedding plus its key
fields), so the system can find **similar invoices**, show a **vendor's history**, flag a
**duplicate invoice number** or an **unusual amount** while the document is validated, and
answer natural-language questions such as *"compare INV-1042 with previous ABC Supplies
invoices"* in a **chat with the Query Agent** that opens from a floating button on every
page. This is the brief's RAG bonus (B3: past invoices in a vector DB). It closes the
0004–0009 limitation "each document is checked against itself only" and the 0000 note
"`embed` is recorded, but nothing calls it until B3".

## Goals

- A new **`modules/retrieval`** that owns the **`invoice_embeddings`** table, building and
  storing each document's embedding, similarity search, vendor matching and history, and
  the deterministic **vendor-history checks**.
- **Index every completed invoice / receipt** automatically at the end of its agent run; a
  reprocess replaces its entry; a one-off command back-fills documents processed before
  0010.
- **Deterministic vendor-history checks** in the Document Agent (new tool
  `check_vendor_history`): duplicate invoice number from the same vendor, amount far outside
  the vendor's usual range, first invoice from a vendor. Results are validation issues, so
  they flow into the validation status, confidence, the summary and the UI unchanged.
- **Similar invoices in the summary:** the Document Agent calls `search_similar_invoices`
  before `generate_summary`, and the summary mentions the closest earlier invoices.
- A **Query Agent** in the `agent` module, on the shared `AgentRunner`, with tools
  `search_invoices` and `get_vendor_history`: answers questions about the stored invoices
  with **cited documents**, **numbers computed by code**, **memory within one chat**, and a
  clear "I can't answer that" for questions outside the invoice data.
- Every embedding and query-loop call goes through `app/core/llm.py` with an `Agent` and
  `Purpose` label, so it shows in the 0007 ledger, trace and metrics.
- UI: a **floating "Ask AI" chat** on every page (one chat, clear / new chat, no history
  list), **Vendor history** + **Similar invoices** on the document detail page, and a small
  retrieval block on the Metrics page.
- Tests use `FakeLLM` (chat + embeddings) and seeded invoices; never the real OpenAI API.

## Non-Goals

- A separate vector database (Pinecone, Qdrant, Chroma) — pgvector in the existing Postgres
  is enough at this size (Prioritization Log, 2026-10-26).
- Chunked / per-page retrieval over raw document text (see D2).
- Fuzzy or LLM-based vendor matching (see D4).
- A list of past conversations, renaming or reopening old chats, or memory across chats
  (see D8, D11).
- Streaming answers token by token.
- Live exchange rates — amounts across currencies use 0004's static, dated rate table.
- Changing the brief's result shape `{document_id, structured_data, validation, summary}`.
- Extraction / Validation / Reporting agents, the Coordinator and `AGENT_MODE=multi` —
  **B4 (0011)**. The Validation and Reporting lanes already map `check_vendor_history` and
  `search_similar_invoices`, so B4 can pick the tools up as they are.
- Authentication.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/retrieval/`: `router.py`, `service.py`, `schema.py`, `crud.py`, `model.py` (D1) | Vector DB outside Postgres |
| Migration: `invoice_embeddings` (pgvector `vector(1536)`, HNSW cosine index), `query_conversations`, `query_runs`, `llm_calls.query_run_id` (D2, D9) | Chunk / line-item vectors |
| One "invoice card" text per document, embedded with `text-embedding-3-small` (D2) | Embedding raw text or the summary |
| Indexing at the end of each completed run; replace on reprocess; back-fill command (D3, D12) | A background job queue |
| Vendor matching by tax ID, then normalised name (D4) | Fuzzy / LLM vendor matching |
| `check_vendor_history` + `search_similar_invoices` in the Document Agent, both guarded; 3 new validation issue codes; `AGENT_MAX_STEPS` 12 → 14; prompt bumps (D5, D6) | Changing 0004's existing rules or 0008's confidence formula |
| Hybrid search: SQL filters + vector ranking + identifier keyword match (D7) | Full-text `tsvector` search |
| Query Agent (`agent` module): `search_invoices`, `get_vendor_history`, `submit_answer`; chat memory within one conversation (D8) | Memory across conversations, streaming |
| `POST /query`, `GET /conversations/{id}`, `GET /documents/{id}/similar`, `GET /documents/{id}/vendor-history` (D10) | A conversation list, a vendors page |
| `Agent.QUERY`, `Purpose.QUERY_EMBEDDING`; retrieval block in `/metrics/summary` (D13) | A per-query trace page |
| UI: floating chat; Vendor history + Similar invoices on the detail page; Metrics retrieval block (D11) | Editing vendors or merging vendor names |
| Tests with `FakeLLM` and seeded invoices / vectors | Real OpenAI calls in tests |
| README, ENGINEERING_NOTES 0010 sections, folder-structure reference | — |

## User Stories

1. **As a reviewer**, I want to be warned when an invoice number from the same vendor was
   already processed, so that I do not pay an invoice twice.
2. **As a reviewer**, I want to be warned when an invoice's total is far outside what this
   vendor usually charges, so that I look at it before approving.
3. **As a reviewer**, I want to see a vendor's previous invoices, their usual range and the
   most similar earlier invoices next to the invoice I am checking (and in its summary), so
   that I can compare without searching.
4. **As a finance user**, I want to open a chat from any page and ask "how much did we pay
   ABC Supplies this year?", then follow up with "and last year?", and get answers that link
   to the invoices they used, so that I can trust and check them.
5. **As a finance user**, I want to clear the chat and start over, so that an old topic does
   not confuse the next question.
6. **As an operator**, I want to see how many documents are indexed and what embeddings and
   questions cost on the Metrics page.

## Product Decisions

> **Status: final.** D1–D14 answered by the user on 2026-10-27 and signed off as final: **D6 changed to B** (the Document Agent also calls `search_similar_invoices`
> for the summary); **D8 = A + C** (everything in A, plus memory within a conversation);
> **D11 changed** to a floating chat button with one chat that can be cleared, no history
> list (D9, D10 adjusted to match); all others as recommended.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Module shape: a new full `modules/retrieval`** (`router`, `service`, `schema`, `crud`, `model`) owns `invoice_embeddings`, the card text, embedding calls, search, vendor matching, history stats and the `check_vendor_history` logic (pure code). **The Query Agent lives in `modules/agent`** (new `query.py` + prompts + `query_conversations` / `query_runs` crud and model) and reuses `AgentRunner` and the `Tool` type as they are. Dependency is one-way: `agent` → `retrieval.service`; `retrieval` imports only `documents` / `structured_extraction` / `validation` services and schemas — never `agent`. | Matches the feature map and the Agent Design roster ("Query Agent … lives in the agent module"), keeps one owner per table, and leaves B4 free to give the same tools to the Validation / Reporting agents. Alternative: put everything in `agent` (fewer files, but `agent` grows past ~1,500 lines and owns a table that is not about runs). |
| D2 | **One vector per document, from a deterministic "invoice card".** Code builds a short text from the final extraction: type, vendor, tax ID, invoice number, dates, currency, total, and up to 30 line-item descriptions (≈ 100–400 tokens). Model `text-embedding-3-small`, **1536 dimensions** (fixed in the migration), **cosine distance**, **HNSW index** (`vector_cosine_ops`). The card text and its SHA-256 are stored. | The card holds exactly what "similar invoice" means (same vendor, same kind of goods, similar amount) and none of the noise of raw text (addresses, bank details, OCR errors, injected instructions); it is stable across prompt changes, unlike the LLM summary. HNSW needs no training step and stays fast as the table grows. Alternatives: raw text, the summary, per-line-item vectors. |
| D3 | **Index at the end of every completed run, in code (not an agent tool).** After the run completes, the same background task writes the document's `invoice_embeddings` row (fields + card + vector). The vector is the one `search_similar_invoices` already computed in the run (D6), so a normal upload makes **one** embedding call. **The embedding call is best-effort:** if it fails, the row is kept with `embedding = null` (vendor history still works) and the document stays `completed`; the back-fill command fills it later. **Reprocess replaces** the row; the embedding call is skipped when the card hash is unchanged. **Not indexed:** failed runs and `document_type = unknown`. `needs_review` documents are indexed **and flagged** (shown with a badge in history and answers). | Indexing is bookkeeping, so code does it and the model cannot skip it. A failed embedding must never fail a good extraction. The hash check means a reprocess with the same result costs nothing. |
| D4 | **Vendor identity: tax ID first, then normalised name; no fuzzy match.** Two documents have the same vendor when their **normalised tax IDs** are equal (upper-case, spaces / dashes / dots removed), **or** their **normalised names** are equal (lower-case, punctuation removed, legal suffixes like *Sdn Bhd, Bhd, Ltd, Pte, Inc, LLC, Co, Corp* removed) **and** they do not both have different tax IDs. The match rule used is shown in the UI ("matched by tax ID" / "matched by name"). | A duplicate-invoice warning on the wrong vendor is worse than a missed one, so matching stays exact and explainable. Tax IDs are the strongest key on Malaysian invoices (SST / TIN); names cover receipts without one. |
| D5 | **`check_vendor_history`: three deterministic rules, written as new validation issues** (0004 catalogue: codes added, never renamed). (a) **`duplicate_invoice_number`** — *warning*, field `invoice_number`: another indexed document from the same vendor has the same normalised invoice number; the message names it (filename, date, total). (b) **`amount_outlier`** — *warning*, field `total_amount`: needs **≥ 5** earlier invoices from the vendor with a total; totals are compared **in the base currency** (static rate table; unsupported currencies are skipped); flagged when the total is outside the **box-plot fences** (Q1 − 1.5 × IQR, Q3 + 1.5 × IQR) **and** at least 25 % away from the median; the message gives the median and the usual range. (c) **`new_vendor`** — *info*, field `vendor`: no earlier invoice from this vendor. The issues are appended to the run's `ValidationReport` (status recomputed with 0004's rule), so **confidence** (0008 validation component), **needs_review**, the **summary coverage check** (warnings must be mentioned) and the Issues list all use them with no new code paths. Only documents **processed before this one** count as history. | Reuses the 0004 contract end to end. The box-plot rule is easy to explain ("outside the vendor's normal range") and robust to one odd invoice; 5 invoices is the smallest history where a range means something; the 25 % gap stops tiny ranges from flagging every small change. A duplicate stays a warning because a legitimate re-upload must not fail validation. |
| D6 | **Document Agent (user's choice B): vendor-history check and similar invoices before the summary, both guarded.** New order: `extract_text` → `extract_tables` → `extract_structured_data` → `check_grounding` → `validate_invoice` → **`check_vendor_history`** → (`convert_currency`) → **`search_similar_invoices`** → `generate_summary`. `generate_summary` refuses (recoverable `history_check_required` / `similar_search_required`) until both have run for the current extraction. `search_similar_invoices` builds this document's card, embeds it (purpose `embedding`; the vector is kept for indexing, D3) and returns the **top 3** earlier invoices above the similarity threshold — vendor, invoice number, date, total and similarity only, never their text. If the embedding fails the tool still succeeds with `available: false`, so the summary is never blocked. `generate_summary` gets the similar invoices and may add **one sentence** about them (e.g. "It is similar to 3 earlier ABC Supplies invoices, most recently INV-1038 on 2026-09-02."); numbers are copied, never computed. Both tools sit in the Validation / Reporting lanes. **`AGENT_MAX_STEPS` 12 → 14** (happy path 9 turns). Prompts: `agent.document.v4`, `agent.summary.v3`. | The user wants the summary itself to compare the document with earlier ones. Guards keep the order in code, as in 0008 / 0009. Embedding once inside the tool and reusing the vector for indexing keeps the cost to one embedding call per upload. Cost: one more model turn per document. |
| D7 | **Search: hybrid.** `search_invoices` takes optional **SQL filters** (vendor, date range, currency, min / max total in the base currency, document type) plus an optional **free-text query** that is embedded (purpose `query_embedding`) and ranked by cosine similarity. Identifiers (invoice numbers, filenames, document IDs) are also matched **exactly / by prefix** in SQL, because embeddings are poor at codes. **top-k 5 (max 20); minimum similarity 0.30**; results below it are dropped (filter-only searches have no threshold). `search_similar_invoices(document_id)` uses the document's own vector, itself excluded (top 3 for the summary, top 5 for the detail page). | Most real questions are filters ("ABC Supplies, this year, over RM 1,000"); vectors help with fuzzy wording ("cleaning services"). Exact ID matching fixes the classic RAG miss on "INV-1042". |
| D8 | **Query Agent (user's choice A + C): sync answers through a `submit_answer` tool, with memory within one conversation.** `POST /query {question, conversation_id?, document_id?}` (question 3–500 chars). No `conversation_id` starts a new conversation; the response returns its ID. **Memory:** the agent sees the conversation's **last 10 turns** (question, answer, cited document IDs); older turns are dropped from the prompt, and nothing is shared between conversations. `document_id` is the page the user is on (see D11), so "this invoice" can be resolved. Tools: `search_invoices` and `get_vendor_history` (accepts a `document_id`, an invoice number or a vendor name; returns the vendor's invoices plus **code-computed aggregates**: count, sum, min, max, median, average in the base currency, and where the target invoice sits). The agent ends by calling **`submit_answer {answer, cited_document_ids, answerable}`**, so `AgentRunner` stays unchanged. **Code checks:** cited IDs must have appeared in a tool result in this conversation (others are dropped); every number in the answer must appear in a tool result of this conversation, else one retry, else the answer is returned with `numbers_verified: false`; `answerable: false` gives a polite "I can only answer questions about the stored invoices". **Max 6 steps per turn** (`QUERY_MAX_STEPS`). Tool results contain structured fields only (never raw text), and the prompt treats them and earlier turns as data, not instructions. Response: `{conversation_id, turn_id, question, answer, answerable, numbers_verified, citations: [{document_id, filename, vendor, invoice_number, invoice_date, total_amount, currency, needs_review}], steps, usage, duration_ms}`. | A turn takes 2–4 model turns (≈ 3–10 s), short enough for one request. Memory lets follow-ups ("and last year?", "which one was the biggest?") work naturally; 10 turns bounds the prompt size and cost. "AI does the thinking, code does the maths": aggregates come from SQL, the model only words them, and code verifies citations and numbers (Domain Rule 4). |
| D9 | **Storage.** `invoice_embeddings`: one row per document (`document_id` unique, cascade), `run_id` (FK `agent_runs`, set null), display + normalised vendor fields, `invoice_number` (+ normalised), `document_type`, `invoice_date`, `currency`, `total_amount` `NUMERIC(14,2)`, `total_base` + `base_currency` (static-rate conversion, null when unsupported), `needs_review`, `card` (text), `card_hash`, `card_version` (`retrieval.card.v1`), `embedding vector(1536)` **nullable**, `embedding_model`, timestamps. Chats: **`query_conversations`** (`id`, `created_at`, `updated_at`) and **`query_runs`** — one row per turn (`id`, `conversation_id` FK cascade, `turn` number, `question`, `document_id` (context, set null), `status`, `answer`, `answerable`, `numbers_verified`, `citations` JSONB, `steps` JSONB, `model`, `prompt_version`, tokens, `error_code` / `error`, `started_at`, `finished_at`). `llm_calls` gains a nullable **`query_run_id`** FK so query calls are in the ledger. | `agent_runs.document_id` is required and a question is not about one document, so separate tables keep both clean. Memory is read from `query_runs`, so it survives a page reload without trusting history sent by the browser. One row per document (replaced) is all search needs. A nullable vector lets history work even when an embedding failed (D3). |
| D10 | **API (brief shapes unchanged).** `POST /api/query` → 200 `QueryResponse` (D8); 404 unknown `conversation_id`; 422 empty / too long; 502 `llm_not_configured`. `GET /api/conversations/{id}` → its turns (question, answer, citations, flags) so the chat can be restored after a reload. `GET /api/documents/{id}/similar?limit=5` → similar invoices with a similarity score (409 `not_indexed` before indexing). `GET /api/documents/{id}/vendor-history` → the vendor, match rule, earlier and later invoices, stats in the base currency, and this invoice's position (computed live). No conversation list endpoint. `GET /result` and `AgentResult` keep their keys; the new issues appear inside `validation`. | Small read endpoints feed the detail page and the chat without making `/result` heavier; the brief's result shape stays as it is. |
| D11 | **UI (user's choice): a floating "Ask AI" chat, not a page.** (a) **Floating button** bottom-right on every page; it opens a chat panel (a full-screen sheet at 375 px). **One chat only:** messages with the user's questions and the answers; each answer shows **cited invoices as links** to their detail pages (vendor, number, date, total, review badge), a "numbers not verified" note when needed, and a collapsible "How I found this" list of tool steps. **"New chat"** clears it and starts a new conversation (the old one is no longer shown; its rows stay in the database for costs and metrics). **No list of past conversations.** The open conversation is kept across page navigation and reloads (its ID in `sessionStorage`, restored with `GET /conversations/{id}`). Empty chat shows 3–4 example questions built from real indexed vendors (static fallback); on a document detail page one example is about **this invoice**, and questions send its `document_id` as context. States: thinking, error with retry, empty index ("No invoices indexed yet"). Keyboard: Esc closes, focus moves into the panel and back. (b) **Detail page:** a **Vendor history** section next to the Issues (match rule, count, median and usual range, a short list of earlier invoices with links, this invoice's position, the duplicate / outlier warnings linking to the other invoice) and a **Similar invoices** list (top 5, similarity shown as text, not colour alone). Old documents: "Reprocess or run the back-fill to index this document". (c) **Agent lanes:** `check_vendor_history` maps to the Validation lane, `search_similar_invoices` to the Reporting lane (already in `lib/agents.ts`). (d) **Metrics:** a small retrieval block (D13). Light + dark, 375 px. | The chat is always one click away, wherever the user is looking, without a separate page or a history list to manage. Knowing the current document makes "compare this invoice with earlier ones" work without copying IDs. |
| D12 | **Back-fill: a one-off command** `uv run python -m app.modules.retrieval.backfill` that indexes every completed document without a row (or with `embedding = null`), using each one's latest completed run. Cost is about **$0.00001 per document** (≈ 300 tokens at $0.02 / 1M). Documents are indexed in upload order; the command does **not** re-run `check_vendor_history` or the summary on old documents (their stored results stay as they were). | Existing demo data becomes searchable at almost no cost, and the same command repairs failed embeddings (D3). |
| D13 | **Observability.** New `Agent.QUERY` label; the Query Agent loop uses `Purpose.AGENT_LOOP` with agent `query`; card embeddings use `Purpose.EMBEDDING` (linked to the document and run); question embeddings use a new `Purpose.QUERY_EMBEDDING` (linked to the query run). `/metrics/summary` and the Metrics page add a **retrieval** block: documents indexed / not embedded, vendor-history issues raised (duplicates, outliers), conversations, questions (count, failed, unanswerable, avg duration, avg cost per question). Tokens and cost stay in the existing by-purpose / by-agent tables. Same `?days=` window. | Reuses the 0007 ledger, so B3's cost is visible without new counters. |
| D14 | **Scope guard:** B4 (Extraction / Validation / Reporting agents, Coordinator, `AGENT_MODE=multi`) and authentication stay out of 0010. | Keeps 0010 to the brief's RAG bonus. |

## Constraints

- Layering: router → service → crud → model; `service.py` never imports FastAPI.
- Cross-module: `agent` calls `retrieval.service`; `retrieval` imports other modules'
  `service` / `schema` only and never imports `agent` (no cycles).
- All OpenAI access, including embeddings, stays in `app/core/llm.py`; every call has an
  `Agent`, a `Purpose` and (for chat) a `prompt_version`.
- Vendor matching, the vendor-history checks, aggregates and currency conversion are
  deterministic code — same data, same output. The model never does arithmetic.
- Domain Rule 4 ("never invent values"): answers cite only documents returned by a tool in
  the conversation; numbers in answers and summaries are checked against tool results.
- Stored document text reaches the agents only as structured fields; tool results and
  earlier chat turns are data, never instructions.
- Bounded cost: one embedding call per uploaded document (skipped on an unchanged card), one
  per searched question; `QUERY_MAX_STEPS` = 6 per turn; memory = last 10 turns;
  `top_k` ≤ 20.
- Money as `Decimal`; UUID v4 PKs; timezone-aware timestamps; errors use the shared
  `{error: {code, message}}` shape; routes under `/api`.
- Frontend: one typed API client, TanStack Query, Tailwind tokens, light + dark, 375 px;
  the chat panel is keyboard-accessible; similarity and warnings never shown by colour alone.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | A completed run writes one `invoice_embeddings` row with the card, hash, normalised vendor / invoice number, base-currency total and a 1536-d vector (FakeLLM), reusing the vector from `search_similar_invoices` (one embedding call per upload); the ledger row has purpose `embedding`, the document and run IDs | service tests |
| 2 | A failed embedding keeps the row with `embedding = null`, `search_similar_invoices` returns `available: false`, and the document still completes; a reprocess replaces the row and skips the embedding call when the card hash is unchanged; `unknown` documents and failed runs are not indexed | service + agent tests |
| 3 | Vendor matching: same tax ID → match; same normalised name → match unless both tax IDs differ; suffix / punctuation / case differences normalise | unit tests |
| 4 | `check_vendor_history` raises `duplicate_invoice_number`, `amount_outlier` (≥ 5 earlier invoices, fences + 25 % gap, base currency, unsupported currencies skipped) and `new_vendor` exactly per D5; only earlier documents count; the report status is recomputed | unit + service tests |
| 5 | `generate_summary` before `check_vendor_history` / `search_similar_invoices` returns the recoverable `history_check_required` / `similar_search_required`; a scripted happy path fits in `AGENT_MAX_STEPS = 14`; the summary coverage check requires the new warnings; the summary prompt receives the top-3 similar invoices | agent tests (FakeLLM) |
| 6 | `search_invoices` applies each SQL filter, ranks by cosine similarity, drops results under 0.30, matches invoice numbers exactly; `search_similar_invoices` excludes the document itself | crud + service tests (seeded vectors) |
| 7 | `POST /query` with a scripted FakeLLM returns an answer, citations limited to IDs seen in the conversation's tool results, `numbers_verified` per D8, `answerable: false` for an off-topic question, and stores a `query_runs` row; a second question with the same `conversation_id` gets the earlier turns in its prompt (at most 10), a new conversation does not; unknown `conversation_id` → 404; ledger rows carry agent `query` and the `query_run_id`; the step limit ends with a clear error | router + service tests |
| 8 | `GET /conversations/{id}` returns the turns in order; `GET /documents/{id}/similar` and `/vendor-history` return the D10 shapes (409 `not_indexed` before indexing; 404 unknown id); `GET /result` keeps its keys | router tests |
| 9 | The back-fill command indexes completed documents without a row and fills null embeddings, and is idempotent | service test |
| 10 | `/metrics/summary` returns the retrieval block for seeded data and respects `?days=` | service + router tests |
| 11 | `alembic upgrade head` creates `invoice_embeddings` (with the HNSW index), `query_conversations` and `query_runs`, and adds `llm_calls.query_run_id` | migration test |
| 12 | `retrieval` imports no other module's `crud` / `model` and nothing from `agent`; `retrieval.service` imports nothing from FastAPI | import test |
| 13 | Floating chat (open / close / Esc, ask, follow-up, answer with cited links, steps, New chat clears, restored after reload, document context on a detail page, loading / error / empty states), detail-page Vendor history + Similar invoices, Metrics retrieval block | Vitest + browser check (desktop + 375 px, light + dark) |
| 14 | `ruff check`, `ruff format --check`, `pytest`, `npm run lint`, `typecheck`, `test` (also with `TZ=UTC`), `build` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B3, after B1 / B2 / B5 so every embedding and query call is
traced and indexed values are grounded; before B4, which reuses these tools).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0010-retrieval-plan.md` | Plan | Implementation path (written after this PRD is final) |
| `docs/prd/0000-setup-prd.md` | Intent | pgvector, `OPENAI_EMBEDDING_MODEL`, `LLMClient.embed`, `FakeLLM.embed` |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | `InvoiceData`, `extractions` |
| `docs/prd/0004-validation-prd.md` | Intent | Issue catalogue, status rule, static rate table |
| `docs/prd/0005-agent-prd.md` | Intent | `AgentRunner`, tools, guards, `agent_runs` |
| `docs/prd/0006-frontend-prd.md` | Intent | Detail page sections, agent lanes, API client |
| `docs/prd/0007-observability-prd.md` | Intent | `llm_calls` ledger, `Agent` / `Purpose` labels, metrics |
| `docs/prd/0008-guardrails-prd.md` | Intent | Confidence, `needs_review`, summary coverage |
| `docs/prd/0009-vision-prd.md` | Intent | Tool order, `AGENT_MAX_STEPS` 12 |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD (next: 0011) |

## Open Questions

None — D1–D14 answered by the user on 2026-10-27 (new `retrieval` module; one card vector per
document, HNSW cosine; indexing in code at the end of each run; tax ID then normalised name;
three vendor-history validation issues; **the Document Agent also calls
`search_similar_invoices` for the summary** (user's choice); hybrid search; **Query Agent with
memory within one conversation** (user's choice); `query_conversations` + `query_runs`;
**a floating "Ask AI" chat with one clearable conversation, no history list** (user's choice);
back-fill command; retrieval metrics; B4 / auth out of scope). Signed off as final on 2026-10-27.

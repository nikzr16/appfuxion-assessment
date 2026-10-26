# 0001 Documents PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Let a user upload a financial document (PDF, JPG, or PNG) and get back an ID they can
poll, so the processing pipeline (0002–0005) has a stored file and a status record to
work on. This is brief Part 1: Document Upload API.

## Goals

- `POST /api/documents` accepts one multipart file, stores it, creates a `documents`
  row, schedules the pipeline in the background, and returns
  `{document_id, status: "processing"}`.
- `GET /api/documents/{id}` returns one document's metadata and status.
- `GET /api/documents` lists documents, newest first, paginated.
- Reject unsupported types (415) and oversized files (413) before anything is stored.
- A pipeline hook that 0005 can replace with the real agent without changing this
  module's router or service.

## Non-Goals

- Text extraction, structured data, validation, summary (0002–0005).
- Exposing pipeline results in `GET /documents/{id}` — 0005 extends the read schema.
- Deleting or re-processing documents.
- Auth, per-user ownership, rate limiting.
- A job queue, retries, or recovery of documents stuck in `processing` after a crash.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/documents/` (router, service, schema, crud, model, pipeline hook) | Pipeline logic (0002–0005) |
| `documents` table + Alembic migration | Result columns / tables (0005) |
| `app/core/storage.py`: save under a caller-given name, never overwrite | Other storage backends (S3) |
| Upload checks: type (header + magic bytes), size, empty file | Virus scanning, PDF sanitising |
| Status lifecycle helpers (`processing` → `completed` / `failed`) used by the pipeline | `DELETE`, re-run endpoints |
| List with `limit` / `offset` / optional `status` filter | Full-text search, sorting options |
| Service + router tests on real Postgres | Frontend upload page (0006) |

## User Stories

1. **As a user**, I want to upload an invoice and get an ID right away, so that I am not
   blocked while it is processed.
2. **As a user**, I want to check a document's status by ID, so that I know when results
   are ready or why it failed.
3. **As a user**, I want a clear error when I upload the wrong file type or a file that
   is too large, so that I can fix it.
4. **As a developer of 0005**, I want one function to plug the agent into, so that the
   upload API does not change when the pipeline arrives.

## Product Decisions

| Decision | Rationale |
|---|---|
| **ID:** native Postgres `UUID` primary key, **UUID v4**, shown in the API as the plain UUID with dashes and no prefix (e.g. `7f3e2b1a-4c5d-4e6f-8a9b-0c1d2e3f4a5b`) | Project-wide rule: every table uses a UUID v4 primary key. Standard form, easy to copy and query; v4 is in the Python stdlib (no new dependency); "newest first" uses `created_at`. Replaces the earlier `doc_` prefix rule |
| **Type check:** magic bytes decide the type; the `Content-Type` header must be an allowed type **and** agree with them; otherwise 415 | The header alone is client-controlled and easy to get wrong; sniffing the first bytes (`%PDF-`, `\x89PNG`, `\xFF\xD8\xFF`) is cheap and stops renamed files reaching the parser |
| **Stored `content_type`** is the sniffed type | The pipeline (0002) routes PDF vs image on it, so it must be trustworthy |
| **Empty file** → 422 `validation_failed` | Distinct from "wrong type"; the user simply sent nothing |
| **Size:** reject when bytes > `MAX_UPLOAD_MB` (default 10) → 413 | Domain rule; limit comes from config |
| **`POST` returns 202 Accepted** with `{document_id, status: "processing"}` | The work continues after the response; body matches the brief exactly |
| **List:** `limit` (default 20, max 100) + `offset`, ordered `created_at DESC, id DESC`; optional `status` filter; response `{items, total, limit, offset}` | Simple, enough for the UI table (0006); `total` lets the UI show page counts |
| **Storage naming:** the file is saved under its **real (cleaned) name** | Files on disk are recognisable by a person; requires `app/core/storage.py` to accept a caller-given name |
| **Name cleaning:** keep only the basename (any client path is dropped: `../../secret.pdf` → `secret.pdf`), replace characters outside letters, digits, `.`, `-`, `_`, `(`, `)`, space with `_`, trim to 255 chars; missing/empty → `upload` | The real name is used on disk, so it must never be able to escape `STORAGE_DIR` or break the filesystem |
| **Duplicates allowed:** every upload is a new document | Re-uploading after a failure must work |
| **Same name → version suffix:** first upload keeps its name (`invoice.pdf`); later uploads of the same name get `(2)`, `(3)`, … before the extension, no space (`invoice(2).pdf`, `invoice(3).pdf`). No `(1)`. The suffix is added to whatever the name is: `invoice_v2.pdf` uploaded twice → `invoice_v2.pdf`, `invoice_v2(2).pdf` | User preference: familiar "copy" style; the history of re-uploads is visible on disk and in the API |
| **Name matching is case-sensitive:** `Invoice.pdf` and `invoice.pdf` are different names, each starting at version 1 | User preference |
| **Never overwrite:** if the disk name for a version is already taken (e.g. on a case-insensitive Windows disk `Invoice.pdf` clashes with `invoice.pdf`, or someone uploads a file literally named `invoice(2).pdf`), the upload takes the next free version | A clash must never replace another document's file; these are rare edge cases |
| **API shows** `filename` = the cleaned uploaded name (`invoice.pdf`) and `version` (`2`); the versioned disk name stays internal | The user sees what they uploaded plus which copy it is |
| **Concurrent same-name uploads** get distinct versions (unique constraint on `(filename, version)`; retry on conflict) | Two simultaneous uploads must not get the same version |
| **Pipeline hook:** a callable `(document_id: UUID) -> None` provided by a FastAPI dependency; a service wrapper runs it in its own DB session, binds the `document_id` log context, and marks the document `failed` (with the error message) if it raises | 0005 swaps one dependency; failure handling lives in one place; tests override the dependency |
| **Completion is the pipeline's job:** the hook marks `completed` when it has saved its results; the 0001 stub is a no-op, so documents stay `processing` until 0005 | Avoids reporting `completed` with no results; 0005 can mark completion in the same transaction as its results |
| **`storage_path` is internal** — not returned by the API | Server layout is not part of the contract |
| **Status column:** `VARCHAR` + `CHECK` constraint, Python `StrEnum` | Easier to extend in migrations than a Postgres enum type |

## Constraints

- Layering: router → service → crud → model; the service never imports FastAPI.
- Tests run on real Postgres and never call OpenAI (this module makes no LLM calls).
- Error responses use the shared shape `{error: {code, message}}`.
- All routes live under `/api`.
- Starlette spools the whole multipart body before the route runs, so the size check
  protects storage and the DB, not server memory/disk for the request itself (documented
  limitation; a reverse-proxy body limit is the production fix).

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | `POST /api/documents` with a valid PDF, JPG, or PNG returns 202 and `{document_id, status: "processing"}`; `document_id` is a UUID v4 string with no prefix | router test |
| 2 | The file is saved under `STORAGE_DIR` with its cleaned real name, and a `documents` row exists with `filename`, `version`, sniffed `content_type`, `size_bytes`, `storage_path`, `status = processing` | service test |
| 2a | Uploading `invoice.pdf` three times stores `invoice.pdf`, `invoice(2).pdf`, `invoice(3).pdf` with versions 1, 2, 3; `invoice_v2.pdf` uploaded twice stores `invoice_v2.pdf`, `invoice_v2(2).pdf`; `Invoice.pdf` is version 1 of its own name; no existing file is ever overwritten | service test |
| 2b | A client name with a path or unsafe characters is cleaned and stays inside `STORAGE_DIR` | service test |
| 3 | Unsupported type, or header/magic-bytes mismatch → 415 `unsupported_media_type`; nothing stored | router + service tests |
| 4 | File larger than `MAX_UPLOAD_MB` → 413 `payload_too_large`; nothing stored | router + service tests |
| 5 | Empty file → 422 `validation_failed`; missing `file` field → 422 `request_validation_failed` | router tests |
| 6 | The pipeline hook is called once with the new `document_id` after the response | router test (overridden dependency) |
| 7 | A hook that raises leaves the document `failed` with a non-empty `error` | service test |
| 8 | `GET /api/documents/{id}` returns the document; unknown id → 404 `not_found`; an id that is not a UUID → 422 `request_validation_failed` | router test |
| 9 | `GET /api/documents` returns newest first with `total`, honours `limit`/`offset`/`status`; `limit` > 100 → 422 | router + service tests |
| 10 | `uv run alembic upgrade head` creates `documents` with the `CHECK` constraint on `status` | migration test |
| 11 | `ruff check`, `ruff format --check`, `pytest` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 1 — Core Pipeline (brief Parts 1–5)

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0001-documents-plan.md` | Plan | Implementation path for this PRD |
| `docs/prd/0000-setup-prd.md` | Intent | Foundation this module builds on (storage, errors, DB, logging) |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — decisions agreed with the user on 2026-10-26 (stub leaves documents
`processing`; UUID v4 without prefix; real file names with `(N)` copy suffixes,
case-sensitive).

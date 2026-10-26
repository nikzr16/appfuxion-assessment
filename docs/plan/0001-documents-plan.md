# 0001 Documents Implementation Plan

> **Type:** Plan | **Must stay current:** No -- record divergences in decision log, rewrite only during re-planning

<!-- AI Context
Role: This document describes *how* to build the feature, not *what* or *why*.
Read the corresponding PRD first for intent and constraints, then use this plan
to guide implementation order, component boundaries, and technical decisions.
Do not rewrite this document during coding. If the implementation diverges from
this plan, add an entry to the decision log instead. Only rewrite during a
deliberate re-planning session.
-->

## Overview

Add the `documents` module (all five DTO layers plus a small `pipeline.py` hook), one
Alembic migration for the `documents` table, a `save_as` method on the core storage, and
service + router tests. Reuses the 0000 foundation: `app.core.storage`,
`app.core.errors` (415/413/404/422), `app.core.db` (`Base`, `SessionLocal`, `get_db`),
`app.core.logging` (`bind_document_id`), and `app.core.config` (`max_upload_bytes`).
No new dependencies.

## Technical Approach

### Layers
`model.py`, `crud.py`, `schema.py`, `service.py`, `router.py`, plus `pipeline.py` —
justified because the hook is the module's extension point for 0005 and must be
importable without pulling in the router. Name cleaning and type sniffing are private
helpers in `service.py`.

### IDs
`id` is `Uuid` (`sqlalchemy.Uuid`, native Postgres `UUID`) with `default=uuid.uuid4`.
The service generates it up front (`uuid.uuid4()`) so the log context has it before the
insert. DTOs type it as `uuid.UUID`, so the API returns the plain dashed string. The path
parameter is typed `UUID`: a malformed id is a 422 from FastAPI, an unknown one a 404 from
the service. The API field is `document_id` in every DTO (matches the brief's final shape).

### Sync routes and size limit
Routes are `def` (the DB and storage are sync; FastAPI runs them in its threadpool). The
router reads `file.file.read(max_upload_bytes + 1)` — one byte over the limit is enough to
detect "too large" — and passes an internal `UploadedFile` DTO (`filename`,
`content_type`, `data`) to the service.

### Type sniffing
First bytes: `%PDF-` → `application/pdf`, `\x89PNG\r\n\x1a\n` → `image/png`,
`\xFF\xD8\xFF` → `image/jpeg`. Header normalisation: lower-case, drop `; params`,
`image/jpg` → `image/jpeg`. Accept only if header ∈ allowed **and** header == sniffed.
The sniffed type is stored.

### Name cleaning (`_clean_filename`)
1. Take the part after the last `/` or `\` (drops any client path).
2. Replace every character that is not a letter/digit (`str.isalnum`) or one of
   `. - _ ( )` or space with `_`.
3. Strip leading/trailing spaces and dots (no hidden files; Windows rejects trailing
   dots/spaces).
4. Windows reserved stems (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, any case) get a
   `_` prefix — the backend also runs on the Windows dev machine.
5. Trim the stem (keep the extension) so the name is ≤ 200 UTF-8 bytes, leaving room for a
   `(N)` suffix under the 255-byte filesystem limit.
6. Empty result → `upload`.

### Versioned disk names
`_disk_name(filename, version)`: version 1 → `filename`; version N → `stem(N)ext`, using
the last extension only (`invoice.pdf` → `invoice(2).pdf`, `invoice_v2.pdf` →
`invoice_v2(2).pdf`, `report.tar.gz` → `report.tar(2).gz`, `notes` → `notes(2)`).

### Upload algorithm (`create_document`)
```
check empty → 422 · size → 413 · type → 415          (nothing stored on any rejection)
filename = _clean_filename(upload.filename)
version  = crud.max_version(db, filename) + 1         (exact, case-sensitive match; 0 if none)
loop (max 20 attempts):
    disk = _disk_name(filename, version)
    try storage.save_as(disk, data)                   (exclusive create — never overwrites)
    except FileExistsError: version += 1; continue    (Windows case clash, literal "invoice(2).pdf")
    try crud.create(...); db.commit(); break
    except IntegrityError:                            (concurrent upload took this version)
        db.rollback(); storage.delete(disk); version = crud.max_version(...) + 1; continue
    except Exception: db.rollback(); storage.delete(disk); raise
after 20 attempts → AppError("Could not allocate a file name") (500)
```
Unique constraints back this up: `(filename, version)` and `storage_path`.

### Core storage change (`app/core/storage.py`)
Add `save_as(name: str, data: bytes) -> StoredFile` to the `Storage` protocol and
`LocalStorage`: resolves through the existing `_path` guard (must stay directly under
`root`), opens with mode `"xb"` (exclusive create, raises `FileExistsError` if taken),
removes a partial file if the write fails. The existing `save()` stays unchanged.

### Pipeline hook (`pipeline.py`)
```python
DocumentPipeline = Callable[[UUID], None]

def noop_pipeline(document_id: UUID) -> None:  # replaced in 0005
    logger.info("pipeline not wired yet; document stays processing")

def get_document_pipeline() -> DocumentPipeline:  # FastAPI dependency
    return noop_pipeline
```
The router calls `background_tasks.add_task(service.run_pipeline, document_id, pipeline)`.
`service.run_pipeline` opens its own `SessionLocal()` (the request session is closed by
then), binds `document_id` in the log context, calls the hook, and on any exception logs
it and calls `mark_failed` with `f"{type(exc).__name__}: {exc}"` trimmed to 1000 chars. It
never re-raises.

### Status, timestamps
- `DocumentStatus(StrEnum)` in `schema.py`; the model imports it (schema never imports
  the model). Column `String(20)` + `CHECK (status IN ('processing','completed','failed'))`.
- `mark_completed(db, document_id)` / `mark_failed(db, document_id, error)` for 0002–0005.
- `created_at` / `updated_at`: `TIMESTAMP WITH TIME ZONE`, `server_default=now()`,
  `updated_at` also `onupdate=func.now()`.

## System Components

| Component | Responsibility |
|---|---|
| `modules/documents/model.py` | `Document`: `id Uuid PK`, `filename String(255)`, `version Integer`, `storage_path String(255) UNIQUE`, `content_type String(100)`, `size_bytes BigInteger`, `status String(20)` + check, `error Text NULL`, `created_at`, `updated_at`; `UNIQUE (filename, version)`; index on `created_at` |
| `modules/documents/crud.py` | `create`, `get`, `max_version(db, filename)`, `list_(db, *, limit, offset, status)` → `(rows, total)`, `update_status` |
| `modules/documents/schema.py` | `DocumentStatus`, `UploadedFile` (internal), `DocumentUploadResponse {document_id, status}`, `DocumentRead {document_id, filename, version, content_type, size_bytes, status, error, created_at, updated_at}`, `DocumentList {items, total, limit, offset}` |
| `modules/documents/service.py` | `create_document`, `get_document`, `list_documents`, `run_pipeline`, `mark_completed`, `mark_failed`, `_clean_filename`, `_disk_name`, `_sniff_content_type` |
| `modules/documents/pipeline.py` | `DocumentPipeline`, `noop_pipeline`, `get_document_pipeline` |
| `modules/documents/router.py` | `POST /documents` (202), `GET /documents/{document_id}`, `GET /documents` (`limit` 1–100 default 20, `offset` ≥ 0, `status` optional) |
| `app/core/storage.py` | New `save_as` (exclusive create) |
| `app/main.py` | Add `documents_router` to `ROUTERS` |
| `app/models.py` | Import `app.modules.documents.model` for autogenerate |
| `migrations/versions/0002_create_documents.py` | Table, check constraint, both unique constraints, index |

## Processing Flow

```
client ──POST /api/documents (multipart "file")──▶ router
  read ≤ max+1 bytes → UploadedFile → service.create_document(db, storage, upload)
    reject: empty 422 · too big 413 · type 415
    clean name → next version → save_as(disk name) → insert row (processing) → commit
  background_tasks.add_task(service.run_pipeline, id, pipeline)
  ◀── 202 {document_id, status: "processing"}
after the response:
  run_pipeline: own session · bind_document_id · pipeline(id)
    returns → 0001 stub: nothing (stays processing); 0005: saves results + mark_completed
    raises  → mark_failed(id, error)
```

## Dependencies

| Dependency | Purpose |
|---|---|
| `python-multipart` (already present) | Multipart parsing |
| stdlib `uuid` | UUID v4 IDs |

## Implementation Phases

### Phase 1: Storage + data layer
`LocalStorage.save_as` + tests in `tests/core/test_storage.py` (writes, refuses to
overwrite, rejects path escapes). `model.py`, register in `app/models.py`, autogenerate
`0002_create_documents`, review it (check + unique constraints + index), `crud.py`.
Extend `tests/test_migrations.py`: table and constraints exist.

### Phase 2: Service + hook
`schema.py`, `pipeline.py`, `service.py`. `tests/modules/documents/test_service.py`.

### Phase 3: HTTP
`router.py`, wire into `ROUTERS`. `tests/modules/documents/test_router.py`.

### Phase 4: Close-out
`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` green. Update
`docs/reference/folder-structure.md` (module files, routes, `documents` table, `save_as`);
append the 0001 section to `ENGINEERING_NOTES.md` (UUID rule, naming/versioning,
sniffing, hook design; limitations: multipart spooling, stuck-in-`processing` after a
crash, disk name vs DB version can differ on case-insensitive disks); fix the `doc_123`
example in `app/core/logging.py`'s docstring; README API section if it lists endpoints;
decision log only for divergences; roadmap stays `in progress` until you confirm the
merge; commit on `feature/0001-documents`.

## Testing Strategy

- **Fixtures:** reuse `client`, `db_session`, `storage` (temp-dir `LocalStorage`) from
  `conftest.py`. Add a `pipeline_spy` fixture overriding `get_document_pipeline` with a
  recorder. Byte samples built in code (`b"%PDF-1.4\n..."`, PNG signature, JPEG
  `\xFF\xD8\xFF\xE0...`) — no binary files in the repo.
- **Size limit:** override settings to a small limit (e.g. 1 KB) instead of 10 MB
  payloads.
- **`test_service.py`:**
  - happy path: file on disk under the cleaned name, row fields, status `processing`
  - versioning: `invoice.pdf` ×3 → `invoice.pdf`, `invoice(2).pdf`, `invoice(3).pdf`;
    `invoice_v2.pdf` ×2 → `invoice_v2(2).pdf`; no `(1)` ever
  - case: `invoice.pdf` then `Invoice.pdf` → the DB version is computed case-sensitively;
    the test checks whether `tmp_path` is case-insensitive and expects version 1 (Linux/CI)
    or version 2 with `Invoice(2).pdf` (Windows), and that `invoice.pdf` is untouched
  - literal clash: `invoice.pdf` ×2, then upload `invoice(2).pdf` → its disk name is taken,
    so it becomes `invoice(2)(2).pdf` (version 2); original files unchanged
  - cleaning: `../../secret.pdf`, `C:\x\a.pdf`, `inv<>|?.pdf`, `.pdf`, `CON.pdf`,
    very long name, missing name
  - rejections (empty, too big, wrong type, header/magic mismatch) store nothing
  - header normalisation (`image/jpg`, `; charset=…`)
  - DB failure after save → file deleted
  - `get_document` 404; list ordering, `total`, `limit`/`offset`, status filter
  - `run_pipeline` calls the hook with the id; raising hook → `failed` + error;
    `mark_completed` sets status and bumps `updated_at`
- **`test_router.py`:** 202 + body (UUID parses, no prefix); hook called once with that id
  (TestClient runs background tasks before returning); 415, 413, 422 (empty file,
  missing field) in the shared error shape; GET by id includes `filename` + `version`,
  excludes `storage_path`; 404 unknown id; 422 malformed id; list params, `limit=101` → 422.
- No LLM calls in this module.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Case-insensitive disk (Windows dev) | `Invoice.pdf` would overwrite `invoice.pdf` | Exclusive create + next free version; test is disk-aware |
| Real names on disk | Path traversal / invalid names | Cleaning + `_path` guard (must stay directly under `root`) + tests |
| Concurrent same-name uploads | Duplicate version | Unique constraints + retry loop (max 20) |
| Background task uses the closed request session | Errors | `run_pipeline` opens its own session |
| Process dies mid-pipeline | Document stuck in `processing` | Documented limitation; production fix is a queue + stale-job sweeper |
| Multipart body spooled before the size check | Large uploads still hit temp disk | Documented; nginx `client_max_body_size` in production |
| File saved but DB insert fails | Orphan file | Delete in the failure path; tested |

## Roadmap Phase

**Phase:** Phase 1 — Core Pipeline (brief Parts 1–5)

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0001-documents-prd.md` | Intent | Product goals and constraints this plan implements |
| `docs/plan/0000-setup-plan.md` | Plan | Foundation components reused here |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan |

## Open Questions

- [x] Add `client_max_body_size` to `frontend/nginx.conf` now? No — agreed 2026-10-26 to
      leave it to the submission pass and note it in ENGINEERING_NOTES.

# 0001 - Setup implementation details that differ from the 0000 plan

> **Date:** 2026-10-26 | **Status:** Accepted

<!-- AI Context
Role: This is an append-only record of a single implementation divergence.
Each entry captures why the deviation happened and what it affects.
Never edit an existing decision log entry. To reverse a previous decision,
create a new entry that references the original. After adding an entry,
check the impact checklist below and update affected workflow or reference
docs before the session ends.
-->

## Context

Implementing `docs/plan/0000-setup-plan.md` surfaced a few details the plan left open or
where the first choice did not work.

## Decision

1. **API prefix.** All routes are served under `/api` (so `GET /api/health`), set by the `api_prefix` setting (default `/api`).
   The plan said `/health`; the `/api` prefix is what the Vite dev
   proxy and nginx both forward.
2. **Health status codes.** `GET /api/health` returns 200 `{status: "ok", database: "ok"}`
   and 503 with `{status: "degraded", database: "error"}` when `SELECT 1` fails, so Docker and
   load-balancer probes see the failure. The frontend treats the 503 body as data.
3. **Compose database port.** The backend container sets `DB_PORT=5432`, `POSTGRES_HOST=db`,
   and a blank `DATABASE_URL`, overriding `.env`, so a host-side `DB_PORT=5433` does not break
   the container-to-container connection.
4. **Frontend toolchain pins.** Vite 7 (not 8) with `@vitejs/plugin-react` 5, and Vitest
   pinned to `~4.0.18`. Vitest 3 bundles its own Vite 7 whose plugin types clash with Vite 8's,
   and `npm install` of Vitest 4.1.x fails with an npm 10 arborist error
   (`Cannot read properties of null (reading 'edgesOut')`). `npm audit` reports 2 advisories (1 critical, 1 moderate) against
   this Vitest range; they affect the dev-time test runner / mock registration only, not the
   built app or the Docker image; upgrade to Vitest >= 4.1.12 once npm can resolve it.
5. **Extra settings.** `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`, `LOG_LEVEL`, and
   `FRONTEND_PORT` were added to `.env.example` beyond the keys listed in `CLAUDE.project.md`.
6. **Volume names.** The compose volumes are named explicitly (`appfuxion_pgdata`,
   `appfuxion_uploads`) so the standalone db file and the full stack share one data volume.

## Reason

Each keeps the stack working end to end on Windows (developer machine), Linux (CI), and Docker
with the smallest deviation from the plan.

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated
- [ ] No upstream doc update needed

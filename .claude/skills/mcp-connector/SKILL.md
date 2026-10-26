---
name: mcp-connector
description: Connect the harness to an MCP server by adding a validated entry to .mcp.json (stdio or remote), with secrets via env vars. Use when adding, configuring, or managing an MCP connector.
allowed-tools: Read, Write, Edit, Bash
---

# mcp-connector

Wire the harness to a **Model Context Protocol (MCP) server** so agents can call
its tools. An MCP connector is **one entry** under `mcpServers` in the repo-root
`.mcp.json` (Claude Code's project-scoped MCP config). No `.claude/` change is
needed to add a server — but keep this playbook, the agent, and `.mcp.json` in
sync.

This is intentionally **on-demand**: `.mcp.json` ships with `mcpServers: {}` and
you add a real server only when a task/workflow needs one.

## Quick Start

Copy this checklist and track progress:

```
MCP connector progress:
- [ ] Step 1: Confirm the need (which server, which tools, transport)
- [ ] Step 2: Add/update the entry under mcpServers (upsert, never duplicate)
- [ ] Step 3: Keep secrets in env vars (${VAR}); never hardcode
- [ ] Step 4: Verify .mcp.json is valid JSON
- [ ] Step 5: (optional) Verify the server resolves (`claude mcp list`)
- [ ] Step 6: Report the server key, transport, required env vars, reload note
```

## Step 1: Confirm the need

Before editing, establish:

- **server key** — a short, unique, kebab-case name (the `mcpServers` map key).
- **transport** — `stdio` (a local process) or **remote** (`http` / `sse`).
- **launch/connection details** — the command + args, or the URL + headers.
- **required tools** — what the workflow actually needs from the server.

If you don't know the real package/command or URL, **stop and report** what's
missing — do not invent a command or add a placeholder server that will fail to
launch (a broken entry produces connection errors on every session start).

## Step 2: Add or update the entry

`.mcp.json` lives at the **repo root**. Edit the `mcpServers` map. **Upsert**: if
a key already exists, edit it in place — never create a duplicate.

### stdio server (local process)

```json
{
  "mcpServers": {
    "example-stdio": {
      "command": "npx",
      "args": ["-y", "@scope/some-mcp-server@1.2.3"],
      "env": {
        "SOME_API_TOKEN": "${SOME_API_TOKEN}"
      }
    }
  }
}
```

Prefer a pinned package version after verifying the package source; unpinned
`latest` installs can change behavior between sessions.

### remote server (http / sse)

```json
{
  "mcpServers": {
    "example-remote": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${EXAMPLE_TOKEN}"
      }
    }
  }
}
```

Use `"type": "sse"` instead of `"http"` for SSE endpoints. Claude Code expands
`${VAR}` (and `${VAR:-default}`) from the environment when it loads `.mcp.json`.

## Step 3: Secret hygiene (hard rule)

- **Never** hardcode tokens/keys/passwords in `.mcp.json`. Reference them as
  `${ENV_VAR}` and document which vars the operator must export.
- `.mcp.json` is committed and shared; secrets live in the environment (or a
  git-ignored `.env`). See `.gitignore`.

## Step 4: Verify valid JSON

`.mcp.json` must remain parseable or Claude Code will ignore all servers.

```bash
python -c "import json,sys; json.load(open('.mcp.json')); print('mcp.json OK')"
```

Note: the harness `validate-config` script does **not** inspect `.mcp.json` — it
only validates agents/skills/workflows. This JSON check is the connector's own
guardrail.

## Step 5: Verify the server (optional)

If the CLI is available, confirm the server is discovered and, ideally, connects:

```bash
claude mcp list
```

## Step 6: Report

Report the server key, transport, the required env vars the operator must set,
and remind them that **Claude Code must reload the MCP config** (restart the
session / reconnect the server) before the new tools become available.

## Hard Rules

- **Upsert, never duplicate** a `mcpServers` key.
- **Secrets only via env** (`${VAR}`); nothing sensitive committed.
- **Keep `.mcp.json` valid JSON**; verify before finishing.
- **No non-launchable placeholders** — if details are unknown, report instead of
  guessing.
- MCP config is a **client (Claude Code) config**, not a harness capability; it
  correctly lives at the repo root, not under `.claude/`.

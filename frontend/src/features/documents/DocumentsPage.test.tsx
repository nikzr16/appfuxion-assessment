import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { formatTimestamp } from "../../lib/format.ts";
import { mockApi, ok } from "../../test/fetchMock.ts";
import { makeDocument } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const HEALTH = { "GET /health": ok({ status: "ok", database: "ok" }) };

function page(items: ReturnType<typeof makeDocument>[], total = items.length, offset = 0) {
  return ok({ items, total, limit: 20, offset });
}

describe("DocumentsPage", () => {
  it("lists documents with version, type, size, status and upload time", async () => {
    mockApi({
      ...HEALTH,
      "GET /documents": page([
        makeDocument({ document_id: "a", filename: "invoice.pdf", version: 2 }),
        makeDocument({
          document_id: "b",
          filename: "scan.png",
          content_type: "image/png",
          status: "failed",
          error: "no_text_found: No readable text was found.",
        }),
      ]),
    });
    renderApp("/documents");

    expect(await screen.findAllByText("invoice.pdf")).not.toHaveLength(0);
    expect(screen.getAllByText("v2")).not.toHaveLength(0);
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(1);
    expect(screen.getAllByText("no_text_found: No readable text was found.")).not.toHaveLength(0);
    // Local time of the runner, so the test passes in any time zone.
    expect(screen.getAllByText(formatTimestamp(makeDocument().created_at))).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: /invoice\.pdf/ })[0]).toHaveAttribute("href", "/documents/a");
  });

  it("filters by status through the URL", async () => {
    const api = mockApi({ ...HEALTH, "GET /documents": page([makeDocument()]) });
    const { router } = renderApp("/documents");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Failed" }));

    expect(router.state.location.search).toBe("?status=failed");
    await waitFor(() => expect(api.calls.at(-1)?.url).toBe("/api/documents?limit=20&offset=0&status=failed"));
    expect(screen.getByRole("tab", { name: "Failed" })).toHaveAttribute("aria-selected", "true");
  });

  it("pages with Previous / Next and keeps the page in the URL", async () => {
    const items = Array.from({ length: 20 }, (_, index) => makeDocument({ document_id: `d${index}` }));
    const api = mockApi({ ...HEALTH, "GET /documents": page(items, 45) });
    const { router } = renderApp("/documents?status=completed");
    const user = userEvent.setup();

    expect(await screen.findByText("1–20")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /next/i }));

    expect(router.state.location.search).toBe("?status=completed&page=2");
    await waitFor(() => expect(api.calls.at(-1)?.url).toBe("/api/documents?limit=20&offset=20&status=completed"));
  });

  it("shows an empty state with a call to action", async () => {
    mockApi({ ...HEALTH, "GET /documents": page([]) });
    renderApp("/documents");

    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload a document/i })).toHaveAttribute("href", "/");
  });

  it("polls every 10 s only while a row is processing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = mockApi({
      ...HEALTH,
      "GET /documents": [
        page([makeDocument({ status: "processing" })]),
        page([makeDocument({ status: "completed" })]),
      ],
    });
    renderApp("/documents");

    expect(await screen.findByText(/Updating every 10 s/)).toBeInTheDocument();
    expect(api.callsTo("GET /documents")).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(10_000));
    await waitFor(() => expect(api.callsTo("GET /documents")).toHaveLength(2));
    expect(await screen.findAllByText("Completed")).not.toHaveLength(0);

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(api.callsTo("GET /documents")).toHaveLength(2);
    expect(screen.queryByText(/Updating every 10 s/)).not.toBeInTheDocument();
  });
});

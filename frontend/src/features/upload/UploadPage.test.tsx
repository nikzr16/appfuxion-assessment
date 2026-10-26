import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { apiError, deferred, mockApi, ok, type MockResponse } from "../../test/fetchMock.ts";
import { CONFIG, makeDocument, pdfFile } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const BASE = {
  "GET /health": ok({ status: "ok", database: "ok" }),
  "GET /config": ok(CONFIG),
  "GET /documents": ok({ items: [makeDocument({ status: "processing" })], total: 1, limit: 20, offset: 0 }),
};

function fileInput(): HTMLInputElement {
  return screen.getByLabelText(/drag & drop/i);
}

describe("UploadPage", () => {
  it("checks files on the client and sends nothing for rejected ones", async () => {
    const api = mockApi(BASE);
    renderApp("/");
    const user = userEvent.setup({ applyAccept: false });

    await user.upload(fileInput(), [pdfFile("ok.pdf"), new File(["x"], "notes.txt", { type: "text/plain" })]);

    expect(screen.getByText("ok.pdf")).toBeInTheDocument();
    const rejected = screen.getByText("notes.txt").closest("li") as HTMLElement;
    expect(within(rejected).getByText("Not uploaded")).toBeInTheDocument();
    expect(within(rejected).getByText(/Not a supported file/)).toBeInTheDocument();
    expect(within(rejected).queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload 1 file" })).toBeEnabled();
    expect(api.callsTo("POST /documents")).toHaveLength(0);
  });

  it("uses the size limit from /api/config", async () => {
    mockApi({ ...BASE, "GET /config": ok({ ...CONFIG, max_upload_mb: 1 }) });
    renderApp("/");
    const user = userEvent.setup();

    expect(await screen.findByText(/up to 1 MB each/)).toBeInTheDocument();
    await user.upload(fileInput(), pdfFile("big.pdf", 2 * 1024 * 1024));

    expect(screen.getByText(/Larger than the 1 MB limit/)).toBeInTheDocument();
  });

  it("falls back to 10 MB when /api/config fails", async () => {
    mockApi({ ...BASE, "GET /config": apiError(500, "internal_error") });
    renderApp("/");

    expect(screen.getByText(/up to 10 MB each/)).toBeInTheDocument();
  });

  it("refuses more than 5 files at a time", async () => {
    mockApi(BASE);
    renderApp("/");
    const user = userEvent.setup();

    await user.upload(
      fileInput(),
      Array.from({ length: 6 }, (_, index) => pdfFile(`f${index}.pdf`)),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("You can upload up to 5 files at a time.");
    expect(screen.queryByText("f0.pdf")).not.toBeInTheDocument();
  });

  it("uploads two at a time, then opens the list with the new documents", async () => {
    const gate = deferred();
    let count = 0;
    const api = mockApi({
      ...BASE,
      "POST /documents": (): MockResponse => {
        count += 1;
        return { status: 202, body: { document_id: `doc-${count}`, status: "processing" }, wait: gate.promise };
      },
    });
    const { router } = renderApp("/");
    const user = userEvent.setup();

    await user.upload(fileInput(), [pdfFile("a.pdf"), pdfFile("b.pdf"), pdfFile("c.pdf")]);
    await user.click(screen.getByRole("button", { name: "Upload 3 files" }));

    await waitFor(() => expect(api.callsTo("POST /documents")).toHaveLength(2));
    expect(screen.getAllByText("Uploading")).toHaveLength(2);
    gate.resolve();

    expect(await screen.findByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(api.callsTo("POST /documents")).toHaveLength(3);
    expect(router.state.location.pathname).toBe("/documents");
    expect(screen.getByText("3 documents uploaded")).toBeInTheDocument();
  });

  it("stays on the page with a friendly reason when the server refuses, and retries", async () => {
    const api = mockApi({
      ...BASE,
      "POST /documents": [
        apiError(502, "llm_not_configured", "OPENAI_API_KEY is not set"),
        ok({ document_id: "doc-1", status: "processing" }, 202),
      ],
    });
    const { router } = renderApp("/");
    const user = userEvent.setup();

    await user.upload(fileInput(), pdfFile("a.pdf"));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));

    expect(await screen.findByText(/AI processing isn't configured/)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");

    await user.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/documents"));
    expect(api.callsTo("POST /documents")).toHaveLength(2);
  });

  it("is reachable by keyboard and announces what was added", async () => {
    mockApi(BASE);
    renderApp("/");
    const user = userEvent.setup();

    const input = fileInput();
    input.focus();
    expect(input).toHaveFocus();
    expect(input).toHaveAccessibleDescription(/PDF, JPG or PNG/);

    await user.upload(input, pdfFile("a.pdf"));

    await waitFor(() => expect(screen.getByTestId("live-region")).toHaveTextContent("1 file ready to upload"));
  });
});

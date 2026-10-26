import { focusManager } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { apiError, mockApi, ok } from "../../test/fetchMock.ts";
import {
  DOC_ID,
  makeDocument,
  makeInvoice,
  makeResult,
  makeRun,
  makeStep,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const PATH = `/documents/${DOC_ID}`;
const HEALTH = { "GET /health": ok({ status: "ok", database: "ok" }) };

function completedRoutes() {
  return {
    ...HEALTH,
    [`GET /documents/${DOC_ID}`]: ok(makeDocument()),
    [`GET /documents/${DOC_ID}/result`]: ok(makeResult()),
    [`GET /documents/${DOC_ID}/runs`]: ok([makeRun()]),
    [`GET /documents/${DOC_ID}/text`]: ok({
      document_id: DOC_ID,
      raw_text: "INVOICE BL-88731",
      method: "pdf_parser",
      page_count: 1,
    }),
  };
}

describe("DocumentDetailPage — completed", () => {
  it("shows the summary, data, issues and agent lanes", async () => {
    mockApi(completedRoutes());
    renderApp(PATH);

    expect(await screen.findByText(/an invoice from Brightlane Logistics/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "invoice.pdf" })).toBeInTheDocument();
    expect(screen.getByText("Validation: Failed")).toBeInTheDocument();
    expect(screen.getAllByText("MYR 1,182.60").length).toBeGreaterThan(0);
    expect(screen.getByText("02-10-2026")).toBeInTheDocument();
    const issue = screen.getByRole("button", { name: /Line 2 · amount/ });
    expect(issue).toHaveTextContent(/Expected MYR 450\.00/);
    expect(issue).toHaveTextContent(/Found MYR 480\.00/);
    expect(screen.getByText(/Single mode — the Document Agent played all three roles/)).toBeInTheDocument();
    for (const name of ["Extraction Agent", "Validation Agent", "Reporting Agent"]) {
      expect(screen.getByRole("region", { name: `${name}: Done` })).toBeInTheDocument();
    }
    expect(document.title).toBe("invoice.pdf · Document Intelligence");
  });

  it("highlights the field, row and cell each issue points at", async () => {
    mockApi(completedRoutes());
    renderApp(PATH);
    await screen.findByText(/an invoice from Brightlane Logistics/);

    expect(document.getElementById("issue-target-due_date")).toHaveClass("bg-danger-soft");
    expect(document.getElementById("issue-target-line_items-1")).toHaveClass("bg-warning-soft");
    expect(document.getElementById("issue-target-line_items-1-amount")).toHaveClass("ring-2");
    expect(document.getElementById("issue-target-total_amount")).not.toHaveClass("ring-2");
  });

  it("scrolls to the issue's field when the issue is clicked", async () => {
    mockApi(completedRoutes());
    renderApp(PATH);
    const user = userEvent.setup();
    await screen.findByText(/an invoice from Brightlane Logistics/);
    const target = document.getElementById("issue-target-line_items-1-amount") as HTMLElement;
    const scroll = vi.spyOn(target, "scrollIntoView");

    await user.click(screen.getByRole("button", { name: /Line 2 · amount/ }));

    expect(scroll).toHaveBeenCalled();
    expect(target).toHaveClass("flash-highlight");
  });

  it("loads the raw text only when its section is opened", async () => {
    const api = mockApi(completedRoutes());
    renderApp(PATH);
    const user = userEvent.setup();
    await screen.findByText(/an invoice from Brightlane Logistics/);

    expect(api.callsTo(`GET /documents/${DOC_ID}/text`)).toHaveLength(0);
    await user.click(screen.getByText("Raw text"));

    expect(await screen.findByText("INVOICE BL-88731")).toBeInTheDocument();
    expect(screen.getByText("PDF text layer")).toBeInTheDocument();
  });

  it("shows the converted total when there is a conversion", async () => {
    mockApi({
      ...completedRoutes(),
      [`GET /documents/${DOC_ID}/result`]: ok(
        makeResult({
          structured_data: makeInvoice({ currency: "USD", total_amount: "1592.00" }),
          conversion: {
            original_amount: "1592.00",
            from_currency: "USD",
            to_currency: "MYR",
            rate: "4.085277",
            converted_amount: "6503.76",
            rate_date: "2026-10-26",
            source: "ExchangeRate-API",
          },
        }),
      ),
    });
    renderApp(PATH);

    expect(await screen.findByText("≈ MYR 6,503.76")).toBeInTheDocument();
    expect(screen.getByText("1 USD = 4.085277 MYR")).toBeInTheDocument();
    expect(screen.getByText("26-10-2026")).toBeInTheDocument();
  });

  it("lists earlier runs collapsed", async () => {
    mockApi({
      ...completedRoutes(),
      [`GET /documents/${DOC_ID}/runs`]: ok([
        makeRun({ id: "run-2", trigger: "reprocess" }),
        makeRun({ id: "run-1", status: "failed", error: "no_text_found: No readable text was found." }),
      ]),
    });
    renderApp(PATH);

    expect(await screen.findByText("Earlier runs (1)")).toBeInTheDocument();
    expect(screen.getByText("no_text_found: No readable text was found.")).toBeInTheDocument();
  });
});

describe("DocumentDetailPage — other states", () => {
  it("shows the failure, the reprocess button and partial data", async () => {
    mockApi({
      ...HEALTH,
      [`GET /documents/${DOC_ID}`]: ok(
        makeDocument({ status: "failed", error: "invalid_llm_output: The model returned invalid data." }),
      ),
      [`GET /documents/${DOC_ID}/extraction`]: ok({
        document_id: DOC_ID,
        structured_data: makeInvoice(),
        model: "m",
        prompt_version: "v",
        attempts: 2,
      }),
      [`GET /documents/${DOC_ID}/runs`]: ok([
        makeRun({ status: "failed", steps: [makeStep({ status: "error", error: { code: "invalid_llm_output", message: "bad" } })] }),
      ]),
    });
    renderApp(PATH);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Processing failed");
    expect(alert).toHaveTextContent("The model returned invalid data.");
    expect(alert).toHaveTextContent("invalid_llm_output");
    expect(await screen.findByText("Partial data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reprocess/i })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Extraction Agent: Failed" })).toBeInTheDocument();
  });

  it("shows not found for an unknown document", async () => {
    mockApi({ ...HEALTH, [`GET /documents/${DOC_ID}`]: apiError(404, "not_found") });
    renderApp(PATH);

    expect(await screen.findByRole("heading", { level: 1, name: "Document not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to documents" })).toHaveAttribute("href", "/documents");
  });

  it("polls while processing, then loads the result once and announces it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = mockApi({
      ...completedRoutes(),
      [`GET /documents/${DOC_ID}`]: [ok(makeDocument({ status: "processing" })), ok(makeDocument())],
      [`GET /documents/${DOC_ID}/runs`]: [
        ok([makeRun({ status: "running", finished_at: null, steps: [makeStep()] })]),
        ok([makeRun()]),
      ],
    });
    renderApp(PATH);

    expect(await screen.findByText("Processing your document")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Extraction Agent: Working" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reprocess/i })).toBeDisabled();
    expect(api.callsTo(`GET /documents/${DOC_ID}/result`)).toHaveLength(0);

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(await screen.findByText(/an invoice from Brightlane Logistics/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("live-region")).toHaveTextContent("Processing complete."));
    expect(api.callsTo(`GET /documents/${DOC_ID}/result`)).toHaveLength(1);
    expect(screen.queryByText(/result_not_ready/)).not.toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(api.callsTo(`GET /documents/${DOC_ID}`)).toHaveLength(2);
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = mockApi({
      ...completedRoutes(),
      [`GET /documents/${DOC_ID}`]: ok(makeDocument({ status: "processing" })),
      [`GET /documents/${DOC_ID}/runs`]: ok([makeRun({ status: "running", steps: [] })]),
    });
    renderApp(PATH);
    await screen.findByText("Processing your document");

    act(() => focusManager.setFocused(false));
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(api.callsTo(`GET /documents/${DOC_ID}`)).toHaveLength(1);

    act(() => focusManager.setFocused(true));
    await waitFor(() => expect(api.callsTo(`GET /documents/${DOC_ID}`)).toHaveLength(2));
  });
});

describe("Reprocess", () => {
  it("asks for confirmation, then switches to the processing view", async () => {
    const api = mockApi({
      ...completedRoutes(),
      [`GET /documents/${DOC_ID}`]: [ok(makeDocument()), ok(makeDocument({ status: "processing" }))],
      [`POST /documents/${DOC_ID}/reprocess`]: ok({ document_id: DOC_ID, status: "processing" }, 202),
    });
    renderApp(PATH);
    const user = userEvent.setup();
    await screen.findByText(/an invoice from Brightlane Logistics/);

    await user.click(screen.getByRole("button", { name: /reprocess/i }));
    const dialog = screen.getByRole("dialog", { name: "Reprocess this document?" });
    expect(dialog).toHaveTextContent(/uses OpenAI tokens/);
    expect(api.callsTo(`POST /documents/${DOC_ID}/reprocess`)).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Reprocess" }));

    expect(await screen.findByText("Processing your document")).toBeInTheDocument();
    expect(api.callsTo(`POST /documents/${DOC_ID}/reprocess`)).toHaveLength(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("can be cancelled", async () => {
    const api = mockApi(completedRoutes());
    renderApp(PATH);
    const user = userEvent.setup();
    await screen.findByText(/an invoice from Brightlane Logistics/);

    await user.click(screen.getByRole("button", { name: /reprocess/i }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.callsTo(`POST /documents/${DOC_ID}/reprocess`)).toHaveLength(0);
  });

  it("explains a 409 already_processing and starts polling", async () => {
    mockApi({
      ...completedRoutes(),
      [`POST /documents/${DOC_ID}/reprocess`]: apiError(409, "already_processing"),
    });
    renderApp(PATH);
    const user = userEvent.setup();
    await screen.findByText(/an invoice from Brightlane Logistics/);

    await user.click(screen.getByRole("button", { name: /reprocess/i }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reprocess" }));

    expect(await screen.findByText("Already processing")).toBeInTheDocument();
    expect(screen.getByText("Processing your document")).toBeInTheDocument();
  });
});

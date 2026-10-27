import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { QueryResponse, QueryTurn } from "../../api/types.ts";
import { STORAGE_KEY } from "../../lib/chat.ts";
import { apiError, deferred, mockApi, ok } from "../../test/fetchMock.ts";
import {
  DOC_ID,
  makeDocument,
  makeResult,
  makeRun,
  makeStep,
  makeTrace,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const CONVERSATION = "9b0f3d2a-1c4e-4a9b-8f7d-2e6c5b4a3d21";
const CITED = "5c1d7e9a-3b2f-4d6e-8a1c-0f9e8d7c6b5a";

function makeTurn(overrides: Partial<QueryTurn> = {}): QueryTurn {
  return {
    turn_id: "turn-1",
    turn: 1,
    question: "How much did we pay ABC?",
    document_id: null,
    status: "completed",
    answer: "ABC Supplies billed MYR 400.00 over 2 invoices.",
    answerable: true,
    numbers_verified: true,
    citations: [
      {
        document_id: CITED,
        filename: "abc-1.pdf",
        vendor: "ABC Supplies",
        invoice_number: "INV-1",
        invoice_date: "2026-01-15",
        total_amount: "100.00",
        currency: "MYR",
        needs_review: true,
      },
    ],
    steps: [
      makeStep({ index: 0, tool: "search_invoices", arguments: { vendor: "ABC" }, result: { total_matches: 2 } }),
      makeStep({ index: 1, turn: 2, tool: "submit_answer", result: { accepted: true } }),
    ],
    error_code: null,
    error: null,
    started_at: "2026-10-27T10:00:00+08:00",
    finished_at: "2026-10-27T10:00:04+08:00",
    duration_ms: 4000,
    ...overrides,
  };
}

function makeResponse(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    ...makeTurn(),
    conversation_id: CONVERSATION,
    usage: { prompt_tokens: 100, completion_tokens: 20, embedding_tokens: 0 },
    ...overrides,
  };
}

const BASE = {
  "GET /health": ok({ status: "ok", database: "ok" }),
  "GET /query/suggestions": ok({
    indexed_documents: 3,
    questions: ["How much have we spent with ABC Supplies in total?", "Which invoices were issued in the last 30 days?"],
  }),
};

async function openChat() {
  await userEvent.click(screen.getByRole("button", { name: "Ask AI about your invoices" }));
  return screen.findByRole("dialog", { name: "Ask AI" });
}

describe("Ask AI chat (feature 0010)", () => {
  it("opens with example questions and answers one with linked invoices", async () => {
    const api = mockApi({ ...BASE, "POST /query": ok(makeResponse()) });
    renderApp("/");

    const dialog = await openChat();
    await waitFor(() => expect(within(dialog).getByRole("textbox", { name: "Your question" })).toHaveFocus());
    await userEvent.click(await within(dialog).findByRole("button", { name: /How much have we spent/ }));

    expect(await within(dialog).findByText("ABC Supplies billed MYR 400.00 over 2 invoices.")).toBeInTheDocument();
    const link = within(dialog).getByRole("link", { name: /INV-1 · 15-01-2026 · MYR 100.00/ });
    expect(link).toHaveAttribute("href", `/documents/${CITED}`);
    expect(within(link).getByText("Review")).toBeInTheDocument();
    expect(within(dialog).getByText("Based on 1 invoice")).toBeInTheDocument();
    expect(JSON.parse(api.callsTo("POST /query")[0]!.body as string)).toEqual({
      question: "How much have we spent with ABC Supplies in total?",
      conversation_id: null,
      document_id: null,
    });
    expect(sessionStorage.getItem(STORAGE_KEY)).toBe(CONVERSATION);

    await userEvent.click(within(dialog).getByText("How I found this"));
    expect(within(dialog).getByText("Searched the invoices")).toBeVisible();
    expect(within(dialog).getByText("vendor “ABC” · 2 matches")).toBeVisible();
  });

  it("sends follow-ups in the same conversation and shows a thinking state", async () => {
    const hold = deferred();
    const api = mockApi({
      ...BASE,
      "POST /query": [ok(makeResponse()), { ...ok(makeResponse({ turn_id: "turn-2", question: "And B?" })), wait: hold.promise }],
    });
    renderApp("/");
    const dialog = await openChat();
    const input = within(dialog).getByRole("textbox", { name: "Your question" });

    await userEvent.type(input, "How much did we pay ABC?{Enter}");
    await within(dialog).findByText(/billed MYR 400.00/);
    await userEvent.type(input, "And B?{Enter}");

    expect(await within(dialog).findByText("Searching the invoices…")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Send question" })).toBeDisabled();
    hold.resolve();
    await waitFor(() => expect(within(dialog).queryByText("Searching the invoices…")).not.toBeInTheDocument());
    const second = JSON.parse(api.callsTo("POST /query")[1]!.body as string);
    expect(second.conversation_id).toBe(CONVERSATION);
  });

  it("flags unverified numbers and shows a refusal plainly", async () => {
    mockApi({
      ...BASE,
      "POST /query": [
        ok(makeResponse({ numbers_verified: false })),
        ok(makeResponse({ turn_id: "t2", answerable: false, answer: "I can only answer questions about the invoices.", citations: [] })),
      ],
    });
    renderApp("/");
    const dialog = await openChat();
    const input = within(dialog).getByRole("textbox", { name: "Your question" });

    await userEvent.type(input, "Total for ABC?{Enter}");
    expect(await within(dialog).findByText(/could not be matched to the invoice data/)).toBeInTheDocument();
    await userEvent.type(input, "Capital of France?{Enter}");
    expect(await within(dialog).findByText("I can only answer questions about the invoices.")).toBeInTheDocument();
  });

  it("shows a failed answer with a retry", async () => {
    mockApi({
      ...BASE,
      "POST /query": [apiError(502, "query_failed", "agent_max_steps"), ok(makeResponse())],
    });
    renderApp("/");
    const dialog = await openChat();

    await userEvent.type(within(dialog).getByRole("textbox", { name: "Your question" }), "Total for ABC?{Enter}");
    const alert = await within(dialog).findByRole("alert");
    expect(within(alert).getByText("No answer this time")).toBeInTheDocument();
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await within(dialog).findByText(/billed MYR 400.00/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(dialog).getAllByText("Total for ABC?")).toHaveLength(1);
  });

  it("restores the stored conversation and New chat clears it", async () => {
    sessionStorage.setItem(STORAGE_KEY, CONVERSATION);
    mockApi({
      ...BASE,
      [`GET /conversations/${CONVERSATION}`]: ok({
        conversation_id: CONVERSATION,
        created_at: "2026-10-27T10:00:00+08:00",
        turns: [makeTurn()],
      }),
    });
    renderApp("/");
    const dialog = await openChat();

    expect(await within(dialog).findByText(/billed MYR 400.00/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "New chat" }));
    expect(within(dialog).queryByText(/billed MYR 400.00/)).not.toBeInTheDocument();
    expect(await within(dialog).findByText("Ask about your invoices")).toBeInTheDocument();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("forgets a stored conversation the server no longer has", async () => {
    sessionStorage.setItem(STORAGE_KEY, CONVERSATION);
    const api = mockApi({
      ...BASE,
      [`GET /conversations/${CONVERSATION}`]: apiError(404, "not_found"),
      "POST /query": ok(makeResponse()),
    });
    renderApp("/");
    const dialog = await openChat();

    expect(await within(dialog).findByText("Ask about your invoices")).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull());
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Your question" }), "Total?{Enter}");
    await within(dialog).findByText(/billed MYR 400.00/);
    expect(JSON.parse(api.callsTo("POST /query")[0]!.body as string).conversation_id).toBeNull();
  });

  it("sends the open document as context and closes with Escape", async () => {
    const api = mockApi({
      ...BASE,
      [`GET /documents/${DOC_ID}`]: ok(makeDocument()),
      [`GET /documents/${DOC_ID}/result`]: ok(makeResult()),
      [`GET /documents/${DOC_ID}/runs`]: ok([makeRun()]),
      [`GET /documents/${DOC_ID}/trace`]: ok(makeTrace()),
      "POST /query": ok(makeResponse()),
    });
    renderApp(`/documents/${DOC_ID}`);
    const dialog = await openChat();

    expect(within(dialog).getByText("Questions can refer to “this invoice”.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Your question" }), "Compare this invoice{Enter}");
    await within(dialog).findByText(/billed MYR 400.00/);
    expect(JSON.parse(api.callsTo("POST /query")[0]!.body as string).document_id).toBe(DOC_ID);
    expect(api.callsTo("GET /query/suggestions")[0]!.url).toContain(`document_id=${DOC_ID}`);

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Ask AI" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask AI about your invoices" })).toHaveFocus());
  });

  it("says when nothing is indexed yet and keeps short questions from being sent", async () => {
    mockApi({ ...BASE, "GET /query/suggestions": ok({ indexed_documents: 0, questions: ["x"] }) });
    renderApp("/");
    const dialog = await openChat();

    expect(await within(dialog).findByText(/No invoices are indexed yet/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("list", { name: "Example questions" })).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Your question" }), "hi");
    expect(within(dialog).getByRole("button", { name: "Send question" })).toBeDisabled();
  });
});

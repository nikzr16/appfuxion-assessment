import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { MetricsSummary } from "../../api/types.ts";
import { apiError, mockApi, ok } from "../../test/fetchMock.ts";
import { renderApp } from "../../test/render.tsx";

const HEALTH = { "GET /health": ok({ status: "ok", database: "ok" }) };

function makeMetrics(overrides: Partial<MetricsSummary> = {}): MetricsSummary {
  const group = (key: string, calls: number, tokens: number, cost: string | null) => ({
    key,
    llm_calls: calls,
    failed_calls: 0,
    prompt_tokens: tokens - 100,
    completion_tokens: 100,
    total_tokens: tokens,
    cost_usd: cost,
    cost_complete: cost !== null,
    avg_latency_ms: 1200,
  });
  return {
    window_days: null,
    since: null,
    generated_at: "2026-10-27T02:00:00+08:00",
    ledger_since: "2026-10-27T01:00:00+08:00",
    documents: { total: 6, processing: 1, completed: 4, failed: 1, success_rate: 0.8 },
    runs: { total: 5, running: 0, completed: 4, failed: 1, avg_ms: 9_500, p50_ms: 9_000, p95_ms: 14_200 },
    llm: {
      llm_calls: 24,
      failed_calls: 1,
      prompt_tokens: 8_000,
      completion_tokens: 2_000,
      total_tokens: 10_000,
      cost_usd: "0.006400",
      cost_complete: true,
      error_rate: 1 / 24,
      documents_with_usage: 4,
      avg_tokens_per_document: 2_500,
      avg_cost_per_document: "0.001600",
    },
    by_model: [group("gpt-4.1-mini", 24, 10_000, "0.006400")],
    by_purpose: [group("agent_loop", 16, 6_000, "0.003800"), group("summary", 4, 1_500, "0.001000")],
    prices_as_of: "2026-10-27",
    ...overrides,
  };
}

describe("MetricsPage", () => {
  it("shows the KPI tiles and the usage tables", async () => {
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics()) });
    renderApp("/metrics");

    expect(await screen.findByText("Success rate")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Metrics" })).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("9.5 s")).toBeInTheDocument();
    expect(screen.getByText(/p50 9.0 s · p95 14.2 s/)).toBeInTheDocument();
    expect(screen.getByText("2,500")).toBeInTheDocument();
    expect(screen.getByText("$0.0016")).toBeInTheDocument();
    expect(screen.getByText("4.2%")).toBeInTheDocument();

    const byModel = screen.getByRole("region", { name: "By model" });
    expect(within(byModel).getByRole("rowheader", { name: "gpt-4.1-mini" })).toBeInTheDocument();
    const byPurpose = screen.getByRole("region", { name: "By purpose" });
    expect(within(byPurpose).getByRole("rowheader", { name: "Agent decides next step" })).toBeInTheDocument();
    expect(screen.getByText(/static price table dated 27-10-2026/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Metrics" })).toHaveAttribute("aria-current", "page");
  });

  it("switches the time window through the URL", async () => {
    const api = mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics()) });
    const { router } = renderApp("/metrics");
    await screen.findByText("Success rate");

    await userEvent.click(screen.getByRole("tab", { name: "7 days" }));

    expect(router.state.location.search).toBe("?days=7");
    expect(api.calls.some((call) => call.url.endsWith("/metrics/summary?days=7"))).toBe(true);
  });

  it("shows an empty state when nothing has been processed", async () => {
    const empty = makeMetrics({
      documents: { total: 0, processing: 0, completed: 0, failed: 0, success_rate: null },
      llm: { ...makeMetrics().llm, llm_calls: 0 },
    });
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(empty) });
    renderApp("/metrics");

    expect(await screen.findByText("No data yet")).toBeInTheDocument();
  });

  it("shows an error with a retry", async () => {
    mockApi({ ...HEALTH, "GET /metrics/summary": apiError(500, "internal_error") });
    renderApp("/metrics");

    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});

describe("MetricsPage — guardrails (feature 0008)", () => {
  const guardrails = {
    runs_scored: 4,
    avg_confidence: 0.87,
    by_label: { high: 2, medium: 1, low: 1 },
    needs_review: 1,
    needs_review_rate: 0.25,
    values_checked: 80,
    values_grounded: 72,
    grounding_rate: 0.9,
    grounding_retry_extractions: 1,
    transient_retries: 3,
  };

  it("shows confidence, review share, grounding rate, retries and the label split", async () => {
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics({ guardrails })) });
    renderApp("/metrics");

    const section = await screen.findByRole("region", { name: "Guardrails" });
    expect(within(section).getByText("87%")).toBeInTheDocument();
    expect(within(section).getByText("25%")).toBeInTheDocument();
    expect(within(section).getByText("1 of 4 runs")).toBeInTheDocument();
    expect(within(section).getByText("90%")).toBeInTheDocument();
    expect(within(section).getByText("72 of 80 values found exactly")).toBeInTheDocument();
    expect(within(section).getByText("3")).toBeInTheDocument();
    expect(within(section).getByRole("img", { name: "High: 2 of 4, Medium: 1 of 4, Low: 1 of 4" })).toBeInTheDocument();
    expect(within(section).getByText("2 · 50%")).toBeInTheDocument();
  });

  it("explains when nothing has been checked yet", async () => {
    const empty = {
      ...guardrails,
      runs_scored: 0,
      avg_confidence: null,
      by_label: { high: 0, medium: 0, low: 0 },
      needs_review: 0,
      needs_review_rate: null,
      values_checked: 0,
      values_grounded: 0,
      grounding_rate: null,
      grounding_retry_extractions: 0,
      transient_retries: 0,
    };
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics({ guardrails: empty })) });
    renderApp("/metrics");

    const section = await screen.findByRole("region", { name: "Guardrails" });
    expect(within(section).getByText(/No document in this window has been checked yet/)).toBeInTheDocument();
  });
});

describe("MetricsPage — vision (feature 0009)", () => {
  const vision = {
    layouts_analysed: 4,
    documents_with_line_item_table: 3,
    tables_found: 5,
    line_items_from_table: 18,
    line_items_from_model: 6,
    line_items_table_share: 0.75,
    pages_via_vision: 7,
    multimodal_calls: 2,
  };

  it("shows tables found, line-item sources and vision use", async () => {
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics({ vision })) });
    renderApp("/metrics");

    const section = await screen.findByRole("region", { name: "Vision" });
    expect(within(section).getByText("3 of 4")).toBeInTheDocument();
    expect(within(section).getByText("5 tables found")).toBeInTheDocument();
    expect(within(section).getByText("75%")).toBeInTheDocument();
    expect(within(section).getByText("18 of 24 copied by code")).toBeInTheDocument();
    expect(within(section).getByText("7")).toBeInTheDocument();
    expect(within(section).getByText("2")).toBeInTheDocument();
  });

  it("explains when nothing has been analysed yet", async () => {
    const empty = { ...vision, layouts_analysed: 0, line_items_from_table: 0, line_items_from_model: 0, pages_via_vision: 0 };
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics({ vision: empty })) });
    renderApp("/metrics");

    const section = await screen.findByRole("region", { name: "Vision" });
    expect(within(section).getByText(/No document in this window has been analysed for tables yet/)).toBeInTheDocument();
  });
});

describe("MetricsPage — retrieval (feature 0010)", () => {
  it("shows the index, the vendor-history flags and the questions", async () => {
    const retrieval = {
      documents_indexed: 12,
      documents_embedded: 11,
      documents_not_embedded: 1,
      duplicate_flags: 2,
      outlier_flags: 1,
      new_vendor_flags: 4,
      conversations: 3,
      questions: 7,
      questions_failed: 1,
      questions_unanswerable: 2,
      questions_unverified: 0,
      avg_question_ms: 4_200,
      avg_cost_per_question: "0.001200",
    };
    mockApi({ ...HEALTH, "GET /metrics/summary": ok(makeMetrics({ retrieval })) });
    renderApp("/metrics");

    const section = await screen.findByRole("region", { name: "Retrieval & Ask AI" });
    expect(within(section).getByText("1 without an embedding")).toBeInTheDocument();
    expect(within(section).getByText("2 duplicates, 1 unusual amount")).toBeInTheDocument();
    expect(within(section).getByText("3 chats · 1 failed · 2 off-topic")).toBeInTheDocument();
    expect(within(section).getByText("4.2 s")).toBeInTheDocument();
    expect(within(section).getByText("$0.0012 per question")).toBeInTheDocument();
  });
});

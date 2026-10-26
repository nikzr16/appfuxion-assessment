import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client.ts";
import { makeRun, makeTrace } from "../../test/fixtures.ts";
import { TraceSection } from "./TraceSection.tsx";

function renderSection(props: Partial<Parameters<typeof TraceSection>[0]> = {}) {
  const onRetry = vi.fn();
  const onRunChange = vi.fn();
  render(
    <TraceSection
      trace={makeTrace()}
      isPending={false}
      error={null}
      onRetry={onRetry}
      runs={[makeRun()]}
      runId={undefined}
      onRunChange={onRunChange}
      {...props}
    />,
  );
  return { onRetry, onRunChange };
}

describe("TraceSection", () => {
  it("shows the run's totals and its timeline", () => {
    renderSection();

    const card = screen.getByRole("region", { name: "Trace" });
    expect(within(card).getByText("Processing time").nextSibling).toHaveTextContent("12.0 s");
    expect(within(card).getByText("Queue time").nextSibling).toHaveTextContent("850 ms");
    expect(within(card).getByText("LLM calls").nextSibling).toHaveTextContent("6");
    expect(within(card).getByText("Tokens").nextSibling).toHaveTextContent("2,250");
    expect(within(card).getByText("Est. cost").nextSibling).toHaveTextContent("$0.0014");
    expect(within(card).getByText("Prices as of 27-10-2026")).toBeInTheDocument();

    const timeline = screen.getByRole("list", { name: "Run timeline" });
    const rows = within(timeline).getAllByRole("listitem");
    expect(rows).toHaveLength(10);
    expect(rows[1]).toHaveTextContent("1.Extract text");
    expect(rows[4]).toHaveTextContent("Structured extraction");
    expect(rows[4]).toHaveTextContent("375 tok");
    expect(within(timeline).getAllByText("Agent decides next step")).toHaveLength(4);
    expect(screen.getByText(/Tokens by purpose/)).toBeInTheDocument();
  });

  it("marks failed calls with their error code", () => {
    const trace = makeTrace();
    const failing = makeTrace({
      spans: trace.spans.map((span) =>
        span.kind === "llm" && span.id === "c6" ? { ...span, status: "error", error_code: "llm_error" } : span,
      ),
    });
    renderSection({ trace: failing });

    expect(screen.getByText("llm_error")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Failed")).toHaveLength(1);
  });

  it("explains a run recorded before per-call tracing", () => {
    renderSection({ trace: makeTrace({ llm_calls_recorded: false, spans: [] }) });

    expect(screen.getByText("Token detail not recorded for this run")).toBeInTheDocument();
    expect(screen.getByText("Tokens").nextSibling).toHaveTextContent("1,500"); // run totals
  });

  it("shows when no run has started, while loading, and on error", async () => {
    const { rerender } = render(
      <TraceSection trace={makeTrace({ run: null, spans: [] })} isPending={false} error={null} onRetry={() => {}} runs={[]} runId={undefined} onRunChange={() => {}} />,
    );
    expect(screen.getByText("No agent run has started yet.")).toBeInTheDocument();

    rerender(
      <TraceSection trace={undefined} isPending error={null} onRetry={() => {}} runs={undefined} runId={undefined} onRunChange={() => {}} />,
    );
    expect(screen.getByLabelText("Loading trace")).toBeInTheDocument();

    const onRetry = vi.fn();
    rerender(
      <TraceSection
        trace={undefined}
        isPending={false}
        error={new ApiError(500, "internal_error", "boom", null)}
        onRetry={onRetry}
        runs={undefined}
        runId={undefined}
        onRunChange={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("lets the user pick an earlier run", async () => {
    const { onRunChange } = renderSection({
      runs: [makeRun({ id: "run-2", trigger: "reprocess" }), makeRun({ id: "run-1" })],
    });

    await userEvent.selectOptions(screen.getByRole("combobox"), "run-1");
    expect(onRunChange).toHaveBeenCalledWith("run-1");
  });
});

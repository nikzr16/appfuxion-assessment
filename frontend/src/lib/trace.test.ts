import { describe, expect, it } from "vitest";

import { makeTrace } from "../test/fixtures.ts";
import {
  axisMs,
  axisTicks,
  barGeometry,
  buildTraceRows,
  laneUsage,
  MIN_BAR_PCT,
  planningUsage,
  purposeLabel,
} from "./trace.ts";

describe("buildTraceRows", () => {
  it("keeps start order and nests LLM calls made inside a step", () => {
    const rows = buildTraceRows(makeTrace());
    expect(rows.map(({ span, depth }) => [span.kind, depth])).toEqual([
      ["llm", 0],
      ["tool", 0],
      ["llm", 0],
      ["tool", 0],
      ["llm", 1],
      ["llm", 0],
      ["tool", 0],
      ["llm", 0],
      ["tool", 0],
      ["llm", 1],
    ]);
  });
});

describe("axisMs", () => {
  it("is the run's duration when it has finished", () => {
    expect(axisMs(makeTrace())).toBe(12_000);
  });

  it("grows to now while the run is going, and never ends before the last span", () => {
    const trace = makeTrace();
    const running = makeTrace({
      run: { ...trace.run!, status: "running", finished_at: null, processing_ms: null },
    });
    const start = Date.parse(trace.run!.started_at);
    expect(axisMs(running, start + 20_000)).toBe(20_000);
    expect(axisMs(running, start + 1_000)).toBe(8_230); // the summary step ends at 6,530 + 1,700
  });

  it("is never zero", () => {
    expect(axisMs(makeTrace({ run: null, spans: [] }))).toBe(1);
  });
});

describe("barGeometry", () => {
  it("places a bar by offset and duration as a share of the axis", () => {
    expect(barGeometry(2_500, 5_000, 10_000)).toEqual({ leftPct: 25, widthPct: 50 });
  });

  it("keeps a minimum width and stays inside the track", () => {
    expect(barGeometry(10_000, 0, 10_000)).toEqual({ leftPct: 100 - MIN_BAR_PCT, widthPct: MIN_BAR_PCT });
    expect(barGeometry(0, 0, 10_000).widthPct).toBe(MIN_BAR_PCT);
  });

  it("splits the axis into ticks", () => {
    expect(axisTicks(8_000)).toEqual([0, 2_000, 4_000, 6_000, 8_000]);
  });
});

describe("usage per lane", () => {
  it("counts each call for the role of its step", () => {
    const usage = laneUsage(makeTrace());
    expect(usage.extraction).toEqual({ calls: 1, tokens: 375, cost: "0.000240" });
    expect(usage.reporting).toEqual({ calls: 1, tokens: 375, cost: "0.000240" });
    expect(usage.validation).toBeUndefined();
  });

  it("keeps the agent's own turns apart as planning", () => {
    expect(planningUsage(makeTrace())).toEqual({ calls: 4, tokens: 1_500, cost: "0.000960" });
  });

  it("leaves the cost unknown when no call was priced", () => {
    const trace = makeTrace();
    const unpriced = makeTrace({
      spans: trace.spans.map((span) => (span.kind === "llm" ? { ...span, cost_usd: null } : span)),
    });
    expect(planningUsage(unpriced).cost).toBeNull();
  });
});

describe("purposeLabel", () => {
  it("names known purposes and falls back for others", () => {
    expect(purposeLabel("agent_loop")).toBe("Agent decides next step");
    expect(purposeLabel("vision_transcription")).toBe("Vision transcription");
    expect(purposeLabel("something_new")).toBe("Other LLM call");
  });
});

import { describe, expect, it } from "vitest";

import { makeRun, makeStep } from "../test/fixtures.ts";
import { buildLanes, modeLabel, roleOfStep, runDurationMs, toolLabel } from "./agents.ts";

const statuses = (run: Parameters<typeof buildLanes>[0]) =>
  buildLanes(run).map((lane) => [lane.role, lane.status]);

describe("roleOfStep", () => {
  it("maps tools to the three agent roles", () => {
    expect(roleOfStep(makeStep({ tool: "extract_text" }))).toBe("extraction");
    expect(roleOfStep(makeStep({ tool: "convert_currency" }))).toBe("validation");
    expect(roleOfStep(makeStep({ tool: "generate_summary" }))).toBe("reporting");
    expect(roleOfStep(makeStep({ tool: "something_new" }))).toBe("other");
  });
});

describe("buildLanes", () => {
  it("marks every lane done for a completed run and sums durations", () => {
    const lanes = buildLanes(makeRun());
    expect(lanes.map((lane) => lane.status)).toEqual(["done", "done", "done"]);
    expect(lanes[0]?.steps).toHaveLength(2);
    expect(lanes[0]?.totalMs).toBe(2844);
  });

  it("shows the lane of the latest step as running and later lanes as waiting", () => {
    const run = makeRun({
      status: "running",
      finished_at: null,
      steps: [makeStep({ index: 0, tool: "extract_text" }), makeStep({ index: 1, tool: "validate_invoice" })],
    });
    expect(statuses(run)).toEqual([
      ["extraction", "done"],
      ["validation", "running"],
      ["reporting", "waiting"],
    ]);
  });

  it("starts with extraction running before any step", () => {
    expect(statuses(makeRun({ status: "running", steps: [] }))[0]).toEqual(["extraction", "running"]);
  });

  it("marks the failing lane and lanes never reached", () => {
    const run = makeRun({
      status: "failed",
      steps: [makeStep({ index: 0, tool: "extract_text", status: "error", error: { code: "no_text_found", message: "x" } })],
    });
    expect(statuses(run)).toEqual([
      ["extraction", "failed"],
      ["validation", "skipped"],
      ["reporting", "skipped"],
    ]);
  });

  it("keeps a recoverable step error inside a lane that is done", () => {
    const run = makeRun({
      steps: [
        makeStep({ index: 0, tool: "validate_invoice" }),
        makeStep({ index: 1, tool: "convert_currency", status: "error", error: { code: "unsupported_currency", message: "x" } }),
        makeStep({ index: 2, tool: "generate_summary" }),
      ],
    });
    expect(statuses(run)[1]).toEqual(["validation", "done"]);
  });

  it("adds an Other lane only when an unknown tool ran", () => {
    expect(buildLanes(makeRun())).toHaveLength(3);
    expect(buildLanes(makeRun({ steps: [makeStep({ tool: "mystery" })] }))).toHaveLength(4);
  });
});

describe("labels", () => {
  it("describes the mode and tools", () => {
    expect(modeLabel(makeRun())).toMatch(/Single mode/);
    expect(modeLabel(makeRun({ mode: "multi" }))).toMatch(/Multi-agent/);
    expect(toolLabel("extract_structured_data")).toBe("Extract structured data");
  });

  it("computes run duration", () => {
    expect(runDurationMs(makeRun())).toBe(12_000);
    expect(runDurationMs(makeRun({ finished_at: null }))).toBeNull();
  });
});

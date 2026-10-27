import { describe, expect, it } from "vitest";

import { makeAgentPart, makeMultiRun, makeRun, makeStep, MULTI_STEPS } from "../test/fixtures.ts";
import {
  agentLabel,
  buildLanes,
  modeLabel,
  roleOfStep,
  runDurationMs,
  toolLabel,
  roleOfTool,
} from "./agents.ts";

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

describe("multi-agent lanes (feature 0011)", () => {
  it("takes the role from the step's agent, falling back to the tool", () => {
    expect(roleOfStep(makeStep({ tool: "search_similar_invoices", agent: "validation" }))).toBe("validation");
    expect(roleOfStep(makeStep({ tool: "generate_summary", agent: "document" }))).toBe("reporting");
    expect(roleOfStep(makeStep({ tool: "extract_text", agent: null }))).toBe("extraction");
  });

  it("gives each agent its lane, steps and breakdown", () => {
    const lanes = buildLanes(makeMultiRun());
    expect(lanes.map((lane) => [lane.role, lane.status, lane.steps.length, lane.part?.prompt_version])).toEqual([
      ["extraction", "done", 2, "agent.extraction.v1"],
      ["validation", "done", 1, "agent.validation.v1"],
      ["reporting", "done", 1, "agent.reporting.v1"],
    ]);
  });

  it("shows the first unfinished agent as running while the run goes", () => {
    const run = makeMultiRun({
      status: "running",
      finished_at: null,
      steps: MULTI_STEPS.slice(0, 3),
      agents: [makeAgentPart()],
    });
    expect(statuses(run)).toEqual([
      ["extraction", "done"],
      ["validation", "running"],
      ["reporting", "waiting"],
    ]);
  });

  it("marks the failed agent and the agents that never started", () => {
    const run = makeMultiRun({
      status: "failed",
      steps: MULTI_STEPS.slice(0, 3),
      agents: [makeAgentPart(), makeAgentPart({ agent: "validation", status: "failed", error_code: "agent_max_steps" })],
    });
    expect(statuses(run)).toEqual([
      ["extraction", "done"],
      ["validation", "failed"],
      ["reporting", "skipped"],
    ]);
  });

  it("names agents for the metrics table", () => {
    expect(agentLabel("validation")).toBe("Validation Agent");
    expect(agentLabel("document")).toBe("Document Agent");
    expect(agentLabel("query")).toBe("Query Agent");
    expect(agentLabel("unknown")).toBe("Outside an agent");
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

describe("roleOfTool", () => {
  it("puts the grounding check in the Extraction lane (feature 0008)", () => {
    expect(roleOfTool("check_grounding")).toBe("extraction");
    expect(toolLabel("check_grounding")).toBe("Check grounding");
  });
});

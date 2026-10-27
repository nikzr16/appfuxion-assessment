/**
 * Trace view helpers (PRD 0007 D10, D11): rows and bar geometry for the waterfall timeline,
 * and token / cost totals per agent lane. Pure functions over `GET /trace`.
 */
import type { DocumentTrace, LLMSpan, TraceSpan } from "../api/types.ts";
import { roleOfTool, type AgentRole } from "./agents.ts";
import { costMicros, microsToCost } from "./format.ts";

export interface TraceRow {
  span: TraceSpan;
  /** 1 for an LLM call made inside a tool step (drawn nested under it). */
  depth: 0 | 1;
}

/** Spans in start order; LLM calls inside a step follow that step, indented. */
export function buildTraceRows(trace: DocumentTrace): TraceRow[] {
  return trace.spans.map((span) => ({
    span,
    depth: span.kind === "llm" && span.step_index !== null ? 1 : 0,
  }));
}

/** Length of the time axis: the run's duration, or (while running) up to now. */
export function axisMs(trace: DocumentTrace, now: number = Date.now()): number {
  const ends = trace.spans.map((span) => span.offset_ms + span.duration_ms);
  let total = trace.run?.processing_ms ?? null;
  if (total === null && trace.run) total = now - new Date(trace.run.started_at).getTime();
  return Math.max(1, total ?? 0, ...ends);
}

/** Minimum bar width (% of the track) so a 0 ms call is still visible. */
export const MIN_BAR_PCT = 0.8;

export function barGeometry(
  offsetMs: number,
  durationMs: number,
  axis: number,
): { leftPct: number; widthPct: number } {
  const width = Math.max(MIN_BAR_PCT, (durationMs / axis) * 100);
  const left = Math.min(Math.max(0, (offsetMs / axis) * 100), 100 - width);
  return { leftPct: Math.max(0, left), widthPct: Math.min(width, 100) };
}

/** Tick positions for the axis: 0, ¼, ½, ¾, end (in ms). */
export function axisTicks(axis: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, index) => (axis * index) / count);
}

const PURPOSE_LABEL: Record<string, string> = {
  agent_loop: "Agent decides next step",
  vision_transcription: "Vision transcription",
  structured_extraction: "Structured extraction",
  multimodal_extraction: "Multimodal extraction",
  grounding_retry: "Grounding retry",
  summary: "Summary",
  embedding: "Embedding",
  query_embedding: "Question embedding",
};

/** `structured_extraction` → `Structured extraction`; unknown purposes stay readable. */
export function purposeLabel(purpose: string): string {
  return PURPOSE_LABEL[purpose] ?? "Other LLM call";
}

export interface Usage {
  calls: number;
  tokens: number;
  /** Sum of the known costs as a decimal string; `null` when no call was priced. */
  cost: string | null;
}

const EMPTY_USAGE: Usage = { calls: 0, tokens: 0, cost: null };

function addUsage(total: Usage, span: LLMSpan): Usage {
  const cost =
    span.cost_usd === null
      ? total.cost
      : microsToCost(costMicros(total.cost ?? "0") + costMicros(span.cost_usd));
  return { calls: total.calls + 1, tokens: total.tokens + span.total_tokens, cost };
}

function llmSpans(trace: DocumentTrace): LLMSpan[] {
  return trace.spans.filter((span): span is LLMSpan => span.kind === "llm");
}

/** Tokens and cost per lane: each call counts for the role of the tool step it ran in. */
export function laneUsage(trace: DocumentTrace): Partial<Record<AgentRole, Usage>> {
  const toolOfStep = new Map<number, string>();
  for (const span of trace.spans) if (span.kind === "tool") toolOfStep.set(span.step_index, span.tool);

  const usage: Partial<Record<AgentRole, Usage>> = {};
  for (const span of llmSpans(trace)) {
    if (span.step_index === null) continue;
    const tool = toolOfStep.get(span.step_index);
    if (tool === undefined) continue;
    const role = roleOfTool(tool);
    usage[role] = addUsage(usage[role] ?? EMPTY_USAGE, span);
  }
  return usage;
}

/** The agent's own turns (choosing the next tool), which belong to no lane until B4. */
export function planningUsage(trace: DocumentTrace): Usage {
  return llmSpans(trace)
    .filter((span) => span.step_index === null)
    .reduce(addUsage, EMPTY_USAGE);
}

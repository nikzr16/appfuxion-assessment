/**
 * Multi-agent view (PRD D19): groups an agent run's tool steps into the three agent roles
 * from the Agent Design table. Until B4 ships, one Document Agent plays all three roles, so
 * the role comes from the tool; B4 only has to change `roleOfStep`.
 */
import type { AgentRunRead, ToolStep } from "../api/types.ts";

export type AgentRole = "extraction" | "validation" | "reporting" | "other";
export type LaneStatus = "waiting" | "running" | "done" | "failed" | "skipped";

export const ROLE_ORDER: readonly AgentRole[] = ["extraction", "validation", "reporting"];

export const ROLE_INFO: Record<AgentRole, { name: string; description: string }> = {
  extraction: {
    name: "Extraction Agent",
    description: "Reads the file, extracts the invoice fields and checks them against the text",
  },
  validation: {
    name: "Validation Agent",
    description: "Checks totals, dates and currency; converts the total",
  },
  reporting: { name: "Reporting Agent", description: "Writes the summary" },
  other: { name: "Other tools", description: "Tools outside the three roles" },
};

const ROLE_OF_TOOL: Record<string, AgentRole> = {
  extract_text: "extraction",
  extract_tables: "extraction",
  extract_structured_data: "extraction",
  check_grounding: "extraction",
  validate_invoice: "validation",
  convert_currency: "validation",
  check_vendor_history: "validation",
  generate_summary: "reporting",
  search_similar_invoices: "reporting",
};

export function roleOfTool(tool: string): AgentRole {
  return ROLE_OF_TOOL[tool] ?? "other";
}

export function roleOfStep(step: ToolStep): AgentRole {
  return roleOfTool(step.tool);
}

export interface Lane {
  role: AgentRole;
  steps: ToolStep[];
  status: LaneStatus;
  totalMs: number;
}

export function buildLanes(run: AgentRunRead): Lane[] {
  const steps = [...run.steps].sort((a, b) => a.index - b.index);
  const latest = steps.at(-1);
  const activeRole: AgentRole = latest ? roleOfStep(latest) : "extraction";
  const roles: readonly AgentRole[] = steps.some((step) => roleOfStep(step) === "other")
    ? [...ROLE_ORDER, "other"]
    : ROLE_ORDER;

  return roles.map((role) => {
    const laneSteps = steps.filter((step) => roleOfStep(step) === role);
    let status: LaneStatus;
    if (run.status === "running" && role === activeRole) status = "running";
    else if (run.status === "failed" && role === activeRole) status = "failed";
    else if (laneSteps.length > 0) status = "done";
    else status = run.status === "running" ? "waiting" : "skipped";
    const totalMs = laneSteps.reduce((sum, step) => sum + step.duration_ms, 0);
    return { role, steps: laneSteps, status, totalMs };
  });
}

/** Wall-clock duration of a run, or `null` while it is running. */
export function runDurationMs(run: AgentRunRead): number | null {
  if (!run.finished_at) return null;
  return Math.max(0, new Date(run.finished_at).getTime() - new Date(run.started_at).getTime());
}

export function modeLabel(run: AgentRunRead): string {
  return run.mode === "multi"
    ? "Multi-agent mode — each role is its own agent"
    : "Single mode — the Document Agent played all three roles";
}

/** `extract_structured_data` → `Extract structured data` */
export function toolLabel(tool: string): string {
  const words = tool.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

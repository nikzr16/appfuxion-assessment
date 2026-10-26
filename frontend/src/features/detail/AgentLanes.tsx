import {
  ArrowDown,
  ArrowRight,
  CircleCheck,
  CircleDashed,
  CircleX,
  LoaderCircle,
  ScanText,
  ShieldCheck,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Fragment } from "react";

import type { AgentRunRead } from "../../api/types.ts";
import { Badge, type Tone } from "../../components/ui/Badge.tsx";
import {
  buildLanes,
  ROLE_INFO,
  ROLE_ORDER,
  toolLabel,
  type AgentRole,
  type Lane,
  type LaneStatus,
} from "../../lib/agents.ts";
import { cx } from "../../lib/cx.ts";
import { formatCost, formatDuration, formatTokens } from "../../lib/format.ts";
import type { Usage } from "../../lib/trace.ts";

const ROLE_ICON: Record<AgentRole, LucideIcon> = {
  extraction: ScanText,
  validation: ShieldCheck,
  reporting: Sparkles,
  other: Wrench,
};

const LANE_STATUS: Record<LaneStatus, { tone: Tone; label: string }> = {
  waiting: { tone: "neutral", label: "Waiting" },
  running: { tone: "accent", label: "Working" },
  done: { tone: "success", label: "Done" },
  failed: { tone: "danger", label: "Failed" },
  skipped: { tone: "neutral", label: "Not reached" },
};

function LaneCard({ lane, usage }: { lane: Lane; usage: Usage | undefined }) {
  const Icon = ROLE_ICON[lane.role];
  const info = ROLE_INFO[lane.role];
  const status = LANE_STATUS[lane.status];
  return (
    <section
      aria-label={`${info.name}: ${status.label}`}
      className={cx(
        "flex min-w-0 flex-1 flex-col rounded-xl border bg-surface p-4 transition-colors",
        lane.status === "running" && "border-accent shadow-[0_0_0_3px_var(--accent-soft)]",
        lane.status === "failed" && "border-danger/60",
        (lane.status === "waiting" || lane.status === "skipped") && "border-dashed border-border-strong",
        (lane.status === "done") && "border-border",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={cx(
              "grid size-9 shrink-0 place-items-center rounded-xl",
              lane.status === "waiting" || lane.status === "skipped"
                ? "bg-surface-2 text-fg-subtle"
                : "bg-accent-soft text-accent",
            )}
          >
            <Icon className="size-4.5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-fg">{info.name}</h3>
            <p className="text-xs text-fg-subtle">{info.description}</p>
          </div>
        </div>
        <Badge
          tone={status.tone}
          icon={lane.status === "running" ? <LoaderCircle className="size-3.5 animate-spin" aria-hidden /> : undefined}
        >
          {status.label}
        </Badge>
      </div>

      {lane.steps.length > 0 ? (
        <ol className="mt-3 space-y-1.5">
          {lane.steps.map((step) => (
            <li key={step.index} className="rounded-lg bg-surface-2 px-2.5 py-2 text-sm">
              <div className="flex items-center gap-2">
                {step.status === "ok" ? (
                  <CircleCheck className="size-4 shrink-0 text-success" aria-label="Succeeded" />
                ) : (
                  <CircleX className="size-4 shrink-0 text-danger" aria-label="Failed" />
                )}
                <span className="min-w-0 flex-1 truncate text-fg">
                  <span className="mr-1 text-fg-subtle tabular-nums">{step.index + 1}.</span>
                  {toolLabel(step.tool)}
                </span>
                <span className="shrink-0 text-xs text-fg-subtle tabular-nums">{formatDuration(step.duration_ms)}</span>
              </div>
              {step.error && (
                <p className="mt-1 pl-6 text-xs break-words text-danger">
                  <span className="font-mono">{step.error.code}</span>: {step.error.message}
                </p>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 flex items-center gap-2 text-xs text-fg-subtle">
          <CircleDashed className="size-3.5" aria-hidden />
          {lane.status === "skipped" ? "The run ended before this step." : "No steps yet."}
        </p>
      )}

      {(lane.totalMs > 0 || usage) && (
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-3">
          {lane.totalMs > 0 && (
            <p className="text-xs text-fg-subtle tabular-nums">Total {formatDuration(lane.totalMs)}</p>
          )}
          {usage && (
            <Badge tone="neutral" className="tabular-nums">
              <span className="sr-only">LLM usage: </span>
              {formatTokens(usage.tokens)} tokens · {formatCost(usage.cost)}
            </Badge>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Extraction → Validation → Reporting lanes for one run (PRD D19); null = run not started yet.
 * `usage` adds each lane's LLM tokens and estimated cost from the trace (PRD 0007 D11).
 */
export function AgentLanes({
  run,
  usage,
}: {
  run: AgentRunRead | null;
  usage?: Partial<Record<AgentRole, Usage>>;
}) {
  const lanes: Lane[] = run
    ? buildLanes(run)
    : ROLE_ORDER.map((role, index) => ({
        role,
        steps: [],
        status: index === 0 ? "running" : "waiting",
        totalMs: 0,
      }));

  return (
    <div className="flex flex-col gap-2 md:flex-row md:items-stretch">
      {lanes.map((lane, index) => (
        <Fragment key={lane.role}>
          {index > 0 && (
            <div className="flex items-center justify-center text-fg-subtle" aria-hidden>
              <ArrowDown className="size-4 md:hidden" />
              <ArrowRight className="hidden size-4 md:block" />
            </div>
          )}
          <LaneCard lane={lane} usage={usage?.[lane.role]} />
        </Fragment>
      ))}
    </div>
  );
}

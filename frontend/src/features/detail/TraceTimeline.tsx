import { Bot, CircleCheck, CircleX, Sparkles, Wrench } from "lucide-react";

import type { DocumentTrace, LLMSpan, ToolSpan } from "../../api/types.ts";
import { toolLabel } from "../../lib/agents.ts";
import { cx } from "../../lib/cx.ts";
import { formatCost, formatDuration, formatTokens } from "../../lib/format.ts";
import { axisMs, axisTicks, barGeometry, buildTraceRows, purposeLabel } from "../../lib/trace.ts";

/* One row grid shared by the axis and every span, so bars line up with the ticks.
   Below `sm` the bar track is hidden and each row shows its offset and duration as text. */
const ROW_GRID = "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_8.5rem]";

function StatusIcon({ ok }: { ok: boolean }) {
  return ok ? (
    <CircleCheck className="size-4 shrink-0 text-success" aria-label="Succeeded" />
  ) : (
    <CircleX className="size-4 shrink-0 text-danger" aria-label="Failed" />
  );
}

function Bar({
  offsetMs,
  durationMs,
  axis,
  kind,
  failed,
  title,
}: {
  offsetMs: number;
  durationMs: number;
  axis: number;
  kind: "tool" | "llm";
  failed: boolean;
  title: string;
}) {
  const { leftPct, widthPct } = barGeometry(offsetMs, durationMs, axis);
  return (
    <div className="relative hidden h-6 sm:block" aria-hidden>
      <div className="absolute inset-y-0 left-0 w-full rounded bg-surface-2/60" />
      <div
        title={title}
        className={cx(
          "absolute top-1/2 -translate-y-1/2 rounded",
          kind === "tool" ? "h-3.5" : "h-2",
          failed ? "bg-danger" : kind === "tool" ? "bg-series-tool" : "bg-series-llm",
        )}
        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
      />
    </div>
  );
}

function Timing({ offsetMs, durationMs }: { offsetMs: number; durationMs: number }) {
  return (
    <span className="text-xs text-fg-subtle tabular-nums sm:hidden">
      +{formatDuration(offsetMs)} · {formatDuration(durationMs)}
    </span>
  );
}

function ToolRow({ span, axis }: { span: ToolSpan; axis: number }) {
  const ok = span.status === "ok";
  return (
    <li className={cx(ROW_GRID, "py-1.5")}>
      <div className="flex min-w-0 items-center gap-2">
        <StatusIcon ok={ok} />
        <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent-soft text-accent">
          <Wrench className="size-3.5" aria-hidden />
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-medium break-words text-fg sm:truncate">
            <span className="mr-1 text-fg-subtle tabular-nums">{span.step_index + 1}.</span>
            {toolLabel(span.tool)}
          </span>
          {span.error_code && <span className="block font-mono text-xs text-danger">{span.error_code}</span>}
          <Timing offsetMs={span.offset_ms} durationMs={span.duration_ms} />
        </span>
      </div>
      <Bar
        offsetMs={span.offset_ms}
        durationMs={span.duration_ms}
        axis={axis}
        kind="tool"
        failed={!ok}
        title={`${toolLabel(span.tool)}: ${formatDuration(span.duration_ms)} at +${formatDuration(span.offset_ms)}`}
      />
      <span className="text-right text-xs text-fg-muted tabular-nums">{formatDuration(span.duration_ms)}</span>
    </li>
  );
}

function LLMRow({ span, axis, nested }: { span: LLMSpan; axis: number; nested: boolean }) {
  const ok = span.status === "ok";
  const label = purposeLabel(span.purpose);
  const Icon = span.purpose === "agent_loop" ? Bot : Sparkles;
  return (
    <li className={cx(ROW_GRID, "py-1.5")}>
      <div className={cx("flex min-w-0 items-center gap-2", nested && "pl-6")}>
        <StatusIcon ok={ok} />
        <span className="grid size-6 shrink-0 place-items-center rounded-md bg-surface-2 text-fg-muted">
          <Icon className="size-3.5" aria-hidden />
        </span>
        <span className="min-w-0">
          <span className="block text-sm break-words text-fg sm:truncate">{label}</span>
          <span className="block truncate text-xs text-fg-subtle" title={span.model}>
            <span className="font-mono">{span.model}</span>
            {span.error_code && <span className="ml-1 font-mono text-danger">{span.error_code}</span>}
          </span>
          <Timing offsetMs={span.offset_ms} durationMs={span.duration_ms} />
        </span>
      </div>
      <Bar
        offsetMs={span.offset_ms}
        durationMs={span.duration_ms}
        axis={axis}
        kind="llm"
        failed={!ok}
        title={`${label}: ${formatDuration(span.duration_ms)}, ${formatTokens(span.total_tokens)} tokens`}
      />
      <span className="text-right text-xs text-fg-muted tabular-nums">
        <span className="block">{formatDuration(span.duration_ms)}</span>
        <span className="block text-fg-subtle">
          <span title={`${span.prompt_tokens} prompt + ${span.completion_tokens} completion tokens`}>
            {formatTokens(span.total_tokens)} tok
          </span>
          {" · "}
          {formatCost(span.cost_usd)}
        </span>
      </span>
    </li>
  );
}

function Legend() {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 w-4 rounded bg-series-tool" aria-hidden />
        Tool step
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2 w-4 rounded bg-series-llm" aria-hidden />
        LLM call
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2 w-4 rounded bg-danger" aria-hidden />
        Failed
      </span>
    </div>
  );
}

/** Waterfall of a run: tool steps with their LLM calls nested, on one time axis (PRD D10). */
export function TraceTimeline({ trace, now }: { trace: DocumentTrace; now?: number }) {
  const rows = buildTraceRows(trace);
  const axis = axisMs(trace, now);
  const ticks = axisTicks(axis);

  return (
    <div>
      <div className="hidden sm:block">
        <Legend />
      </div>
      <div className={cx(ROW_GRID, "hidden border-b border-border pb-1.5 sm:grid")} aria-hidden>
        <span className="text-xs font-medium text-fg-subtle">Step</span>
        <div className="relative h-4">
          {ticks.map((tick, index) => (
            <span
              key={tick}
              className={cx(
                "absolute top-0 text-[11px] text-fg-subtle tabular-nums",
                index === 0 ? "left-0" : index === ticks.length - 1 ? "right-0" : "-translate-x-1/2",
              )}
              style={index > 0 && index < ticks.length - 1 ? { left: `${(index / (ticks.length - 1)) * 100}%` } : undefined}
            >
              {formatDuration(tick)}
            </span>
          ))}
        </div>
        <span className="text-right text-xs font-medium text-fg-subtle">Time · tokens · cost</span>
      </div>
      <ol className="divide-y divide-border/60" aria-label="Run timeline">
        {rows.map(({ span, depth }) =>
          span.kind === "tool" ? (
            <ToolRow key={`tool-${span.step_index}`} span={span} axis={axis} />
          ) : (
            <LLMRow key={span.id} span={span} axis={axis} nested={depth === 1} />
          ),
        )}
      </ol>
    </div>
  );
}

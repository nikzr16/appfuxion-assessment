import { Activity, Info } from "lucide-react";
import type { ReactNode } from "react";

import type { AgentRunRead, DocumentTrace } from "../../api/types.ts";
import { Alert, ErrorAlert } from "../../components/ui/Alert.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { cx } from "../../lib/cx.ts";
import { EMPTY, formatCost, formatDate, formatDuration, formatTimestamp, formatTokens } from "../../lib/format.ts";
import { purposeLabel } from "../../lib/trace.ts";
import { TraceTimeline } from "./TraceTimeline.tsx";

function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("min-w-0 rounded-xl bg-surface-2 px-3.5 py-3", className)}>
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="mt-0.5 truncate text-lg font-semibold text-fg tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-fg-subtle tabular-nums">{hint}</dd>}
    </div>
  );
}

function Totals({ trace }: { trace: DocumentTrace }) {
  const { run, totals } = trace;
  const recorded = trace.llm_calls_recorded;
  const runTokens = run ? run.run_prompt_tokens + run.run_completion_tokens : 0;
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      <Stat
        label="Processing time"
        value={run?.processing_ms != null ? formatDuration(run.processing_ms) : run ? "Running…" : EMPTY}
      />
      <Stat
        label="Queue time"
        value={run?.queue_ms != null ? formatDuration(run.queue_ms) : EMPTY}
        hint={run?.trigger === "reprocess" ? "Not tracked for reprocess" : "Upload → agent start"}
      />
      <Stat
        label="LLM calls"
        value={recorded ? totals.llm_calls : EMPTY}
        hint={totals.failed_calls > 0 ? `${totals.failed_calls} failed` : undefined}
      />
      <Stat
        label="Tokens"
        value={recorded ? formatTokens(totals.total_tokens) : formatTokens(runTokens)}
        hint={
          recorded
            ? `${formatTokens(totals.prompt_tokens)} in · ${formatTokens(totals.completion_tokens)} out`
            : "Agent + summary only"
        }
      />
      <Stat
        className="col-span-2 sm:col-span-1"
        label="Est. cost"
        value={recorded ? formatCost(totals.cost_usd) : EMPTY}
        hint={recorded && !totals.cost_complete ? "Some models unpriced" : `Prices as of ${formatDate(trace.prices_as_of)}`}
      />
    </dl>
  );
}

function ByPurpose({ trace }: { trace: DocumentTrace }) {
  if (trace.by_purpose.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-xs text-fg-muted">Tokens by purpose</span>
      {trace.by_purpose.map((group) => (
        <Badge key={group.key}>
          {purposeLabel(group.key)}
          <span className="text-fg-subtle tabular-nums">
            {" "}
            {formatTokens(group.total_tokens)} · {group.llm_calls}×
          </span>
        </Badge>
      ))}
    </div>
  );
}

function RunPicker({
  runs,
  value,
  onChange,
}: {
  runs: AgentRunRead[];
  value: string | undefined;
  onChange: (runId: string | undefined) => void;
}) {
  if (runs.length < 2) return null;
  return (
    <label className="flex items-center gap-2 text-xs text-fg-muted">
      <span className="sr-only sm:not-sr-only">Run</span>
      <select
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || undefined)}
        className="h-8 max-w-56 rounded-lg border border-border bg-surface px-2 text-xs text-fg"
      >
        {runs.map((run, index) => (
          <option key={run.id} value={index === 0 ? "" : run.id}>
            {index === 0 ? "Latest · " : ""}
            {run.trigger === "upload" ? "Upload" : "Reprocess"} · {formatTimestamp(run.started_at)}
          </option>
        ))}
      </select>
    </label>
  );
}

interface TraceSectionProps {
  trace: DocumentTrace | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
  runs: AgentRunRead[] | undefined;
  runId: string | undefined;
  onRunChange: (runId: string | undefined) => void;
}

/** Timing, tokens and estimated cost of one run, with its waterfall timeline (PRD 0007 D10). */
export function TraceSection({ trace, isPending, error, onRetry, runs, runId, onRunChange }: TraceSectionProps) {
  return (
    <Card aria-labelledby="trace-title">
      <CardHeader
        id="trace-title"
        icon={<Activity className="size-4.5" aria-hidden />}
        title="Trace"
        description="Where the time and tokens went: each tool step and the LLM calls made in it."
        actions={runs && <RunPicker runs={runs} value={runId} onChange={onRunChange} />}
      />
      <CardBody>
        {isPending && !trace ? (
          <div className="space-y-3" aria-busy="true" aria-label="Loading trace">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {[0, 1, 2, 3, 4].map((index) => (
                <Skeleton key={index} className="h-18 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-40 rounded-xl" />
          </div>
        ) : error && !trace ? (
          <ErrorAlert error={error} onRetry={onRetry} />
        ) : !trace?.run ? (
          <p className="text-sm text-fg-muted">No agent run has started yet.</p>
        ) : (
          <>
            <Totals trace={trace} />
            <ByPurpose trace={trace} />
            {!trace.llm_calls_recorded && trace.run.status !== "running" && (
              <Alert tone="info" title="Token detail not recorded for this run" className="mt-4">
                This run happened before per-call recording was added, so only its tool steps and
                run-level tokens are shown. Reprocess the document to get a full trace.
              </Alert>
            )}
            <div className="mt-5">
              {trace.spans.length > 0 ? (
                <TraceTimeline trace={trace} />
              ) : (
                <p className="flex items-center gap-2 text-sm text-fg-muted">
                  <Info className="size-4" aria-hidden />
                  Steps appear here as the agent works.
                </p>
              )}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

import { Bot, BrainCircuit, ChevronDown } from "lucide-react";
import { useMemo } from "react";

import type { AgentRunRead, DocumentTrace } from "../../api/types.ts";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { ErrorAlert } from "../../components/ui/Alert.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { modeLabel, runDurationMs } from "../../lib/agents.ts";
import { formatCost, formatDuration, formatRelative, formatTimestamp, formatTokens } from "../../lib/format.ts";
import { laneUsage, planningUsage } from "../../lib/trace.ts";
import { AgentLanes } from "./AgentLanes.tsx";

const RUN_STATUS = {
  running: { tone: "accent", label: "Running" },
  completed: { tone: "success", label: "Completed" },
  failed: { tone: "danger", label: "Failed" },
} as const;

function RunMeta({ run }: { run: AgentRunRead }) {
  const duration = runDurationMs(run);
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
      <Badge tone={RUN_STATUS[run.status].tone}>{RUN_STATUS[run.status].label}</Badge>
      <span>{run.trigger === "upload" ? "Upload" : "Reprocess"}</span>
      <span aria-hidden>·</span>
      <time dateTime={run.started_at} title={formatRelative(run.started_at)} className="tabular-nums">
        {formatTimestamp(run.started_at)}
      </time>
      {duration !== null && (
        <>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{formatDuration(duration)}</span>
        </>
      )}
    </span>
  );
}

interface AgentActivityProps {
  runs: AgentRunRead[] | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
  live: boolean;
  /** The latest run's trace; adds tokens per lane and the planning turns (PRD 0007 D11). */
  trace?: DocumentTrace;
}

/** The multi-agent view of the latest run, plus earlier runs collapsed (PRD D10, D19). */
export function AgentActivity({ runs, isPending, error, onRetry, live, trace }: AgentActivityProps) {
  const latest = runs?.[0] ?? null;
  const earlier = runs?.slice(1) ?? [];
  const usage = useMemo(() => {
    if (!trace?.run || !latest || trace.run.run_id !== latest.id || !trace.llm_calls_recorded) return null;
    return { lanes: laneUsage(trace), planning: planningUsage(trace) };
  }, [trace, latest]);

  return (
    <Card aria-labelledby="agent-activity-title">
      <CardHeader
        id="agent-activity-title"
        icon={<Bot className="size-4.5" aria-hidden />}
        title="Agent activity"
        description={latest ? modeLabel(latest) : "The agents that process this document and the tools they call."}
        actions={latest && <RunMeta run={latest} />}
      />
      <CardBody>
        {isPending && !runs ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-32 rounded-xl" />
            ))}
          </div>
        ) : error && !runs ? (
          <ErrorAlert error={error} onRetry={onRetry} />
        ) : (
          <>
            {usage && usage.planning.calls > 0 && (
              <p className="mb-3 flex flex-wrap items-center gap-x-1.5 text-xs text-fg-muted">
                <BrainCircuit className="size-3.5 text-fg-subtle" aria-hidden />
                <span className="font-medium text-fg">Planning</span>
                <span className="tabular-nums">
                  {usage.planning.calls} {usage.planning.calls === 1 ? "turn" : "turns"} ·{" "}
                  {formatTokens(usage.planning.tokens)} tokens · {formatCost(usage.planning.cost)}
                </span>
                <span className="text-fg-subtle">— the agent choosing each next tool</span>
              </p>
            )}
            <AgentLanes run={latest} usage={usage?.lanes} />
            {live && (
              <p className="mt-3 text-xs text-fg-subtle">Steps appear here as the agents work.</p>
            )}
          </>
        )}

        {earlier.length > 0 && (
          <div className="mt-6 border-t border-border pt-4">
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-fg-muted uppercase">
              Earlier runs ({earlier.length})
            </h3>
            <ul className="space-y-2">
              {earlier.map((run) => (
                <li key={run.id}>
                  <details className="group rounded-xl border border-border">
                    <summary className="flex cursor-pointer list-none items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
                      <span className="min-w-0 flex-1">
                        <RunMeta run={run} />
                        {run.error && (
                          <span className="mt-1 block truncate text-xs text-danger" title={run.error}>
                            {run.error}
                          </span>
                        )}
                      </span>
                      <ChevronDown
                        className="size-4 shrink-0 text-fg-subtle transition-transform group-open:rotate-180"
                        aria-hidden
                      />
                    </summary>
                    <div className="border-t border-border p-3">
                      <AgentLanes run={run} />
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

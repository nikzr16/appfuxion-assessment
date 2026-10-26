import { BarChart3, Clock, Coins, FileStack, Gauge, Hash, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router";

import { useMetrics } from "../../api/queries.ts";
import type { GroupTotals, MetricsSummary } from "../../api/types.ts";
import { PageHeader } from "../../components/PageHeader.tsx";
import { ErrorAlert } from "../../components/ui/Alert.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { EmptyState } from "../../components/ui/EmptyState.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { Tabs, type TabOption } from "../../components/ui/Tabs.tsx";
import {
  EMPTY,
  formatCost,
  formatDate,
  formatDuration,
  formatPercent,
  formatTimestamp,
  formatTokens,
} from "../../lib/format.ts";
import { purposeLabel } from "../../lib/trace.ts";
import { useDocumentTitle } from "../../lib/useDocumentTitle.ts";

type Window = "7" | "30" | "all";

const WINDOWS: readonly TabOption<Window>[] = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "all", label: "All time" },
];

function ms(value: number | null): string {
  return value === null ? EMPTY : formatDuration(value);
}

function Tile({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <Card className="p-4 sm:p-5">
      <dt className="flex items-center gap-2 text-sm text-fg-muted">
        <span className="grid size-7 place-items-center rounded-lg bg-accent-soft text-accent">{icon}</span>
        {label}
      </dt>
      <dd className="mt-3 text-2xl font-semibold tracking-tight text-fg tabular-nums">{value}</dd>
      {hint && <dd className="mt-1 text-xs text-fg-subtle tabular-nums">{hint}</dd>}
    </Card>
  );
}

function Tiles({ data }: { data: MetricsSummary }) {
  const { documents, runs, llm } = data;
  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Tile
        icon={<FileStack className="size-4" aria-hidden />}
        label="Documents"
        value={documents.total}
        hint={`${documents.completed} completed · ${documents.failed} failed · ${documents.processing} processing`}
      />
      <Tile
        icon={<Gauge className="size-4" aria-hidden />}
        label="Success rate"
        value={formatPercent(documents.success_rate)}
        hint="Completed out of finished documents"
      />
      <Tile
        icon={<Clock className="size-4" aria-hidden />}
        label="Avg processing time"
        value={ms(runs.avg_ms)}
        hint={`p50 ${ms(runs.p50_ms)} · p95 ${ms(runs.p95_ms)} · ${runs.completed} completed runs`}
      />
      <Tile
        icon={<Hash className="size-4" aria-hidden />}
        label="Tokens per document"
        value={llm.avg_tokens_per_document === null ? EMPTY : formatTokens(llm.avg_tokens_per_document)}
        hint={`${formatTokens(llm.total_tokens)} tokens in total`}
      />
      <Tile
        icon={<Coins className="size-4" aria-hidden />}
        label="Est. cost per document"
        value={formatCost(llm.avg_cost_per_document)}
        hint={`${formatCost(llm.cost_usd)} in total${llm.cost_complete ? "" : " (some models unpriced)"}`}
      />
      <Tile
        icon={<TriangleAlert className="size-4" aria-hidden />}
        label="LLM error rate"
        value={formatPercent(llm.error_rate)}
        hint={`${llm.failed_calls} failed of ${llm.llm_calls} calls`}
      />
    </dl>
  );
}

function UsageTable({
  id,
  title,
  description,
  keyHeader,
  rows,
  renderKey,
}: {
  id: string;
  title: string;
  description: string;
  keyHeader: string;
  rows: GroupTotals[];
  renderKey: (key: string) => ReactNode;
}) {
  return (
    <Card aria-labelledby={id}>
      <CardHeader id={id} title={title} description={description} />
      <CardBody className="px-0 sm:px-0">
        {rows.length === 0 ? (
          <p className="px-5 text-sm text-fg-muted sm:px-6">No LLM calls in this window.</p>
        ) : (
          <>
            {/* Phones: one stacked entry per row instead of a wide table. */}
            <ul className="divide-y divide-border/60 sm:hidden">
              {rows.map((row) => (
                <li key={row.key} className="px-5 py-3">
                  <p className="text-sm font-medium break-words text-fg">{renderKey(row.key)}</p>
                  <p className="mt-1 text-xs text-fg-muted tabular-nums">
                    {row.llm_calls} calls
                    {row.failed_calls > 0 && <span className="text-danger"> ({row.failed_calls} failed)</span>} ·{" "}
                    {formatTokens(row.total_tokens)} tokens · {formatCost(row.cost_usd)} ·{" "}
                    {formatDuration(row.avg_latency_ms)} avg
                  </p>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto sm:block">
              <table className="w-full min-w-[36rem] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-fg-muted">
                    <th scope="col" className="py-2 pr-3 pl-5 font-medium sm:pl-6">{keyHeader}</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Calls</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Tokens</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Est. cost</th>
                    <th scope="col" className="py-2 pr-5 pl-3 text-right font-medium sm:pr-6">Avg latency</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {rows.map((row) => (
                    <tr key={row.key}>
                      <th scope="row" className="py-2.5 pr-3 pl-5 text-left font-medium text-fg sm:pl-6">
                        {renderKey(row.key)}
                      </th>
                      <td className="px-3 py-2.5 text-right whitespace-nowrap text-fg tabular-nums">
                        {row.llm_calls}
                        {row.failed_calls > 0 && (
                          <span className="block text-xs text-danger">{row.failed_calls} failed</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right whitespace-nowrap text-fg tabular-nums">
                        {formatTokens(row.total_tokens)}
                        <span className="block text-xs text-fg-subtle">
                          {formatTokens(row.prompt_tokens)} in · {formatTokens(row.completion_tokens)} out
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right whitespace-nowrap text-fg tabular-nums">{formatCost(row.cost_usd)}</td>
                      <td className="py-2.5 pr-5 pl-3 text-right whitespace-nowrap text-fg tabular-nums sm:pr-6">
                        {formatDuration(row.avg_latency_ms)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function MetricsSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading metrics">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((index) => (
          <Skeleton key={index} className="h-32 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-56 rounded-2xl" />
    </div>
  );
}

/** Product-wide numbers: documents, success rate, processing time, tokens, cost (PRD 0007 D12). */
export default function MetricsPage() {
  useDocumentTitle("Metrics");
  const [params, setParams] = useSearchParams();
  const raw = params.get("days");
  const range: Window = raw === "7" || raw === "30" ? raw : "all";
  const days = range === "all" ? undefined : Number(range);
  const metrics = useMetrics(days);

  function onWindowChange(value: Window) {
    setParams(value === "all" ? {} : { days: value }, { replace: true });
  }

  const data = metrics.data;
  const empty = data && data.documents.total === 0 && data.llm.llm_calls === 0;

  return (
    <>
      <PageHeader
        title="Metrics"
        description="How documents are processed: success rate, processing time, LLM tokens and estimated cost."
        actions={<Tabs label="Time window" options={WINDOWS} value={range} onChange={onWindowChange} />}
      />

      {metrics.isPending ? (
        <MetricsSkeleton />
      ) : metrics.isError && !data ? (
        <ErrorAlert error={metrics.error} onRetry={() => void metrics.refetch()} />
      ) : empty ? (
        <Card>
          <EmptyState
            icon={<BarChart3 className="size-6" aria-hidden />}
            title="No data yet"
            description={
              range === "all"
                ? "Upload a document and its numbers will show up here."
                : "Nothing was processed in this window. Try a longer one."
            }
          />
        </Card>
      ) : data ? (
        <div className="space-y-6" aria-busy={metrics.isFetching}>
          <Tiles data={data} />
          <div className="space-y-6">
            <UsageTable
              id="metrics-by-model"
              title="By model"
              description="Which models were called and what they cost."
              keyHeader="Model"
              rows={data.by_model}
              renderKey={(key) => <span className="font-mono text-xs">{key}</span>}
            />
            <UsageTable
              id="metrics-by-purpose"
              title="By purpose"
              description="What the LLM calls were for."
              keyHeader="Purpose"
              rows={data.by_purpose}
              renderKey={purposeLabel}
            />
          </div>
          <p className="text-xs text-fg-subtle">
            Costs are estimates from a static price table dated {formatDate(data.prices_as_of)} (cached-input
            discounts ignored).
            {data.ledger_since && (
              <> Token and cost figures cover LLM calls recorded since {formatTimestamp(data.ledger_since)}.</>
            )}{" "}
            Updated {formatTimestamp(data.generated_at)}.
          </p>
        </div>
      ) : null}
    </>
  );
}

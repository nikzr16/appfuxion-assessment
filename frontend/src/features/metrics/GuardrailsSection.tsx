import { RefreshCcw, Repeat, ScanSearch, ShieldCheck, ShieldQuestion } from "lucide-react";
import type { ReactNode } from "react";

import type { ConfidenceLabel, GuardrailMetrics } from "../../api/types.ts";
import { CONFIDENCE_STYLE } from "../../components/confidenceStyle.ts";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { CONFIDENCE_LABEL, formatScore } from "../../lib/confidence.ts";
import { cx } from "../../lib/cx.ts";
import { EMPTY, formatPercent } from "../../lib/format.ts";

const LABELS: readonly ConfidenceLabel[] = ["high", "medium", "low"];

const SEGMENT_COLOR: Record<ConfidenceLabel, string> = {
  high: "bg-conf-high",
  medium: "bg-conf-medium",
  low: "bg-conf-low",
};

export function Stat({ icon, label, value, hint }: { icon: ReactNode; label: string; value: ReactNode; hint: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-surface-2 px-4 py-3">
      <dt className="flex items-center gap-2 text-xs font-medium text-fg-muted">
        <span className="text-accent">{icon}</span>
        {label}
      </dt>
      <dd className="mt-1.5 text-xl font-semibold tracking-tight text-fg tabular-nums">{value}</dd>
      <dd className="mt-0.5 text-xs text-fg-subtle tabular-nums">{hint}</dd>
    </div>
  );
}

/** High / medium / low share of scored runs, with a legend that carries the numbers. */
export function ConfidenceSplit({ byLabel, total }: { byLabel: GuardrailMetrics["by_label"]; total: number }) {
  if (total === 0) return null;
  const share = (label: ConfidenceLabel) => byLabel[label] / total;
  const summary = LABELS.map((label) => `${CONFIDENCE_LABEL[label]}: ${byLabel[label]} of ${total}`).join(", ");
  return (
    <figure className="mt-5">
      <figcaption className="mb-2 text-xs font-medium text-fg-muted">Confidence of completed runs</figcaption>
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full" role="img" aria-label={summary}>
        {LABELS.filter((label) => byLabel[label] > 0).map((label) => (
          <span
            key={label}
            className={cx("h-full min-w-1.5 first:rounded-l-full last:rounded-r-full", SEGMENT_COLOR[label])}
            style={{ flexGrow: byLabel[label], flexBasis: 0 }}
            title={`${CONFIDENCE_LABEL[label]} confidence: ${byLabel[label]} of ${total} runs (${formatPercent(share(label))})`}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-fg-muted">
        {LABELS.map((label) => {
          const { Icon, text } = CONFIDENCE_STYLE[label];
          return (
            <li key={label} className="inline-flex items-center gap-1.5">
              <span className={cx("size-2.5 rounded-sm", SEGMENT_COLOR[label])} aria-hidden />
              <Icon className={cx("size-3.5", text)} aria-hidden />
              <span className="text-fg">{CONFIDENCE_LABEL[label]}</span>
              <span className="tabular-nums">
                {byLabel[label]} · {formatPercent(share(label))}
              </span>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}

/** Extraction quality in the window (feature 0008, PRD D10). */
export function GuardrailsSection({ data }: { data: GuardrailMetrics }) {
  return (
    <Card aria-labelledby="metrics-guardrails">
      <CardHeader
        id="metrics-guardrails"
        icon={<ShieldCheck className="size-4.5" aria-hidden />}
        title="Guardrails"
        description="How far the extracted values can be trusted: found in the document text, confidence, and retries."
      />
      <CardBody>
        {data.runs_scored === 0 && data.values_checked === 0 ? (
          <p className="text-sm text-fg-muted">
            No document in this window has been checked yet. New and reprocessed documents get a grounding check and
            confidence scores.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              <Stat
                icon={<ShieldCheck className="size-4" aria-hidden />}
                label="Avg confidence"
                value={data.avg_confidence === null ? EMPTY : formatScore(data.avg_confidence)}
                hint={`${data.runs_scored} scored run${data.runs_scored === 1 ? "" : "s"}`}
              />
              <Stat
                icon={<ShieldQuestion className="size-4" aria-hidden />}
                label="Needs review"
                value={formatPercent(data.needs_review_rate)}
                hint={`${data.needs_review} of ${data.runs_scored} runs`}
              />
              <Stat
                icon={<ScanSearch className="size-4" aria-hidden />}
                label="Grounding rate"
                value={formatPercent(data.grounding_rate)}
                hint={`${data.values_grounded} of ${data.values_checked} values found exactly`}
              />
              <Stat
                icon={<RefreshCcw className="size-4" aria-hidden />}
                label="Grounding retries"
                value={data.grounding_retry_extractions}
                hint="Extractions re-asked for values not in the text"
              />
              <Stat
                icon={<Repeat className="size-4" aria-hidden />}
                label="Transient retries"
                value={data.transient_retries}
                hint="LLM calls retried after a rate limit, timeout or 5xx"
              />
            </dl>
            <ConfidenceSplit byLabel={data.by_label} total={data.runs_scored} />
          </>
        )}
      </CardBody>
    </Card>
  );
}

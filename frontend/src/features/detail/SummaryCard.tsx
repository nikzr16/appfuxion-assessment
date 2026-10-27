import { Sparkles } from "lucide-react";

import type { AgentResult } from "../../api/types.ts";
import { SEVERITY_STYLE } from "../../components/severity.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card } from "../../components/ui/Card.tsx";
import { EMPTY, formatDate, formatMoney } from "../../lib/format.ts";
import { countBySeverity } from "../../lib/issues.ts";
import { ConfidenceChip } from "./ConfidenceSummary.tsx";
import { DOCUMENT_TYPE_LABELS, VALIDATION_STATUS } from "./labels.ts";

function Fact({
  label,
  value,
  strong = false,
  note,
}: {
  label: string;
  value: string;
  strong?: boolean;
  note?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-fg-subtle">{label}</dt>
      <dd
        className={
          strong
            ? "mt-0.5 truncate text-xl font-semibold text-fg tabular-nums"
            : "mt-0.5 truncate text-sm font-medium text-fg"
        }
        title={value}
      >
        {value}
      </dd>
      {note && <dd className="mt-0.5 text-xs text-fg-muted tabular-nums">{note}</dd>}
    </div>
  );
}

/** The answer first: AI summary, validation status and the key facts (PRD D7). */
export function SummaryCard({ result }: { result: AgentResult }) {
  const data = result.structured_data;
  const status = VALIDATION_STATUS[result.validation.status];
  const counts = countBySeverity(result.validation.issues);

  return (
    <Card aria-labelledby="summary-title" className="overflow-hidden">
      <div className="bg-gradient-to-br from-accent-soft to-transparent px-5 pt-5 pb-5 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="summary-title" className="flex items-center gap-2 text-base font-semibold text-fg">
            <Sparkles className="size-4.5 text-accent" aria-hidden />
            Summary
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{DOCUMENT_TYPE_LABELS[data.document_type]}</Badge>
            <Badge tone={status.tone}>Validation: {status.label}</Badge>
            {result.confidence && <ConfidenceChip report={result.confidence} />}
          </div>
        </div>
        <p className="mt-3 max-w-3xl text-[0.95rem] leading-relaxed text-fg">{result.summary}</p>
        {(counts.error > 0 || counts.warning > 0 || counts.info > 0) && (
          <p className="mt-3 flex flex-wrap gap-2">
            {(["error", "warning", "info"] as const)
              .filter((severity) => counts[severity] > 0)
              .map((severity) => {
                const { tone, label, Icon } = SEVERITY_STYLE[severity];
                return (
                  <Badge key={severity} tone={tone} icon={<Icon className="size-3.5" aria-hidden />}>
                    {counts[severity]} {label.toLowerCase()}
                    {counts[severity] === 1 ? "" : "s"}
                  </Badge>
                );
              })}
          </p>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-border px-5 py-4 sm:px-6 lg:grid-cols-4">
        <Fact
          label="Total"
          value={formatMoney(data.total_amount, data.currency)}
          strong
          note={
            result.conversion
              ? `≈ ${formatMoney(result.conversion.converted_amount, result.conversion.to_currency)}`
              : undefined
          }
        />
        <Fact label="Vendor" value={data.vendor ?? EMPTY} />
        <Fact label="Invoice number" value={data.invoice_number ?? EMPTY} />
        <Fact
          label="Invoice / due date"
          value={`${formatDate(data.invoice_date)} → ${formatDate(data.due_date)}`}
        />
      </dl>
    </Card>
  );
}

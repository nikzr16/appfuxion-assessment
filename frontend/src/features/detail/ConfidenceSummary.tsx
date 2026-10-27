import { ShieldAlert, TextSearch } from "lucide-react";

import type { ConfidenceReport } from "../../api/types.ts";
import { CONFIDENCE_STYLE } from "../../components/confidenceStyle.ts";
import { Alert } from "../../components/ui/Alert.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { CONFIDENCE_LABEL, formatScore, highlightOf } from "../../lib/confidence.ts";
import { issueLocation } from "./labels.ts";
import type { LocateHandler } from "./StructuredData.tsx";

/** Overall confidence in the summary header: label, icon and score (PRD 0008 D9). */
export function ConfidenceChip({ report }: { report: ConfidenceReport }) {
  const { tone, Icon } = CONFIDENCE_STYLE[report.label];
  const { fields, completeness, validation } = report.components;
  return (
    <span
      title={`Overall ${formatScore(report.overall)} = 60% field confidence (${formatScore(fields)}) + 25% completeness (${formatScore(completeness)}) + 15% validation (${formatScore(validation)})`}
    >
      <Badge tone={tone} icon={<Icon className="size-3.5" aria-hidden />}>
        {CONFIDENCE_LABEL[report.label]} confidence · <span className="tabular-nums">{formatScore(report.overall)}</span>
      </Badge>
    </span>
  );
}

/** Lists the fields to check; each one found in the text jumps there. */
export function NeedsReviewBanner({ report, onLocate }: { report: ConfidenceReport; onLocate: LocateHandler }) {
  if (!report.needs_review || report.review_fields.length === 0) return null;
  return (
    <Alert tone="warning" title="Needs review" role="status">
      <p>
        These values could not be confirmed in the document text, or scored low. Check them against the original
        before you use this data.
      </p>
      <ul className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {report.review_fields.map((path) => {
          const field = report.fields[path];
          const span = highlightOf(field);
          const label = issueLocation(path);
          const reason = field?.reasons[0] ?? "Could not be confirmed";
          return (
            <li key={path}>
              {span ? (
                <button
                  type="button"
                  onClick={() => onLocate(span)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-warning/40 bg-surface px-2.5 py-1 text-xs font-medium text-fg hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  title={reason}
                >
                  <TextSearch className="size-3.5 text-warning" aria-hidden />
                  {label}
                  <span className="sr-only">: {reason}. Show in the raw text</span>
                </button>
              ) : (
                <span
                  className="inline-flex items-center gap-1.5 rounded-lg border border-warning/40 bg-surface px-2.5 py-1 text-xs font-medium text-fg"
                  title={reason}
                >
                  <ShieldAlert className="size-3.5 text-warning" aria-hidden />
                  {label}
                  <span className="text-fg-muted">· {reason}</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </Alert>
  );
}

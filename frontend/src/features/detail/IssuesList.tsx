import { CircleCheck, ShieldCheck } from "lucide-react";

import type { ValidationReport } from "../../api/types.ts";
import { SEVERITY_STYLE } from "../../components/severity.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { formatMoney } from "../../lib/format.ts";
import { countBySeverity, revealIssueTarget, sortIssues } from "../../lib/issues.ts";
import { issueLocation, VALIDATION_STATUS } from "./labels.ts";

interface IssuesListProps {
  report: ValidationReport;
  currency: string | null;
}

/** Validation issues, worst first; each one jumps to the value it concerns (PRD D8). */
export function IssuesList({ report, currency }: IssuesListProps) {
  const issues = sortIssues(report.issues);
  const counts = countBySeverity(report.issues);
  const status = VALIDATION_STATUS[report.status];

  return (
    <Card aria-labelledby="validation-title">
      <CardHeader
        id="validation-title"
        icon={<ShieldCheck className="size-4.5" aria-hidden />}
        title="Validation"
        description="Checked by code, not by the AI."
      />
      <CardBody>
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Badge tone={status.tone}>{status.label}</Badge>
          {issues.length > 0 && (
            <span className="text-sm text-fg-muted">
              {(["error", "warning", "info"] as const)
                .filter((severity) => counts[severity] > 0)
                .map(
                  (severity) =>
                    `${counts[severity]} ${SEVERITY_STYLE[severity].label.toLowerCase()}${counts[severity] === 1 ? "" : "s"}`,
                )
                .join(" · ")}
            </span>
          )}
        </div>
        {issues.length === 0 ? (
          <div className="flex items-center gap-3 rounded-xl bg-success-soft p-4 text-sm text-fg">
            <CircleCheck className="size-5 shrink-0 text-success" aria-hidden />
            All checks passed: totals add up, dates and currency look right.
          </div>
        ) : (
          <ul className="space-y-2">
              {issues.map((issue, index) => {
                const { Icon, text, label, tint } = SEVERITY_STYLE[issue.severity];
                return (
                  <li key={`${issue.field}-${issue.code}-${index}`}>
                    <button
                      type="button"
                      onClick={() => revealIssueTarget(issue.field)}
                      className={`w-full rounded-xl p-3 text-left transition-shadow hover:shadow-card ${tint}`}
                    >
                      <span className="flex items-start gap-2.5">
                        <Icon className={`mt-0.5 size-4 shrink-0 ${text}`} aria-hidden />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-x-2 text-xs font-semibold">
                            <span className={text}>{label}</span>
                            <span className="text-fg-muted">{issueLocation(issue.field)}</span>
                          </span>
                          <span className="mt-1 block text-sm text-fg">{issue.message}</span>
                          {issue.expected !== null && issue.actual !== null && (
                            <span className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-fg-muted tabular-nums">
                              <span>
                                Expected <span className="font-medium text-fg">{formatMoney(issue.expected, currency)}</span>
                              </span>
                              <span>
                                Found <span className="font-medium text-fg">{formatMoney(issue.actual, currency)}</span>
                              </span>
                            </span>
                          )}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

import { ChevronRight, CircleAlert, FileText, Info, ListChecks, TriangleAlert } from "lucide-react";
import { Link } from "react-router";

import type { Citation, QueryTurn } from "../../api/types.ts";
import { Badge } from "../../components/ui/Badge.tsx";
import { Button } from "../../components/ui/Button.tsx";
import { describeStep } from "../../lib/chat.ts";
import { cx } from "../../lib/cx.ts";
import { friendlyError } from "../../lib/errors.ts";
import { formatDate, formatMoney } from "../../lib/format.ts";

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm whitespace-pre-line text-accent-fg">
        <span className="sr-only">You asked: </span>
        {text}
      </p>
    </div>
  );
}

function CitationLink({ citation, onNavigate }: { citation: Citation; onNavigate: () => void }) {
  const details = [
    citation.invoice_number ?? citation.filename,
    formatDate(citation.invoice_date),
    formatMoney(citation.total_amount, citation.currency),
  ].join(" · ");
  return (
    <li>
      <Link
        to={`/documents/${citation.document_id}`}
        onClick={onNavigate}
        className="group flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2 transition-colors hover:border-accent/40 hover:bg-accent-soft/40"
      >
        <FileText className="size-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">{citation.vendor ?? citation.filename}</span>
          <span className="block truncate text-xs text-fg-subtle tabular-nums">{details}</span>
        </span>
        {citation.needs_review && <Badge tone="warning">Review</Badge>}
        <ChevronRight className="size-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
      </Link>
    </li>
  );
}

function AnswerSteps({ turn }: { turn: QueryTurn }) {
  if (turn.steps.length === 0) return null;
  return (
    <details className="group mt-3 rounded-lg text-xs text-fg-muted">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-md font-medium hover:text-fg [&::-webkit-details-marker]:hidden">
        <ListChecks className="size-3.5" aria-hidden />
        How I found this
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
      </summary>
      <ol className="mt-2 space-y-1.5 border-l border-border pl-3">
        {turn.steps.map((step) => {
          const line = describeStep(step);
          return (
            <li key={step.index}>
              <span className={cx("font-medium", line.failed ? "text-warning" : "text-fg")}>{line.title}</span>
              {line.detail && <span className="block text-fg-subtle">{line.detail}</span>}
            </li>
          );
        })}
      </ol>
    </details>
  );
}

export function AnswerCard({ turn, onNavigate }: { turn: QueryTurn; onNavigate: () => void }) {
  const refused = turn.answerable === false;
  return (
    <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-border bg-surface-2 px-3.5 py-3">
      <p className="text-sm whitespace-pre-line text-fg">
        {refused && <Info className="mr-1.5 inline size-4 align-[-3px] text-info" aria-hidden />}
        <span className="sr-only">Answer: </span>
        {turn.answer}
      </p>
      {turn.numbers_verified === false && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-warning">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          Some numbers in this answer could not be matched to the invoice data. Check them in the invoices
          below.
        </p>
      )}
      {turn.citations.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-xs font-medium text-fg-muted">
            Based on {turn.citations.length} invoice{turn.citations.length === 1 ? "" : "s"}
          </p>
          <ul className="space-y-1.5">
            {turn.citations.map((citation) => (
              <CitationLink key={citation.document_id} citation={citation} onNavigate={onNavigate} />
            ))}
          </ul>
        </div>
      )}
      <AnswerSteps turn={turn} />
    </div>
  );
}

export function ThinkingBubble() {
  return (
    <div className="flex w-fit items-center gap-2 rounded-2xl rounded-bl-md border border-border bg-surface-2 px-3.5 py-2.5 text-sm text-fg-muted">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="size-1.5 animate-bounce rounded-full bg-accent motion-reduce:animate-none"
            style={{ animationDelay: `${dot * 150}ms` }}
          />
        ))}
      </span>
      Searching the invoices…
    </div>
  );
}

export function ErrorBubble({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { title, message } = friendlyError(error);
  return (
    <div role="alert" className="max-w-[92%] rounded-2xl rounded-bl-md border border-danger/30 bg-danger-soft px-3.5 py-3">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-fg">
        <CircleAlert className="size-4 text-danger" aria-hidden />
        {title}
      </p>
      <p className="mt-1 text-sm text-fg-muted">{message}</p>
      <Button variant="secondary" size="sm" className="mt-2.5" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

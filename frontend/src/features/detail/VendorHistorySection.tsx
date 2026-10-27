import { ChevronRight, Copy, History, Layers } from "lucide-react";
import { Link } from "react-router";

import { useSimilar, useVendorHistory } from "../../api/queries.ts";
import type { IndexEntry, InvoiceHit, SimilarInvoices, VendorHistory } from "../../api/types.ts";
import { ErrorAlert } from "../../components/ui/Alert.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { EMPTY, formatDate, formatMoney } from "../../lib/format.ts";
import { MATCH_RULE_LABEL, positionSentence, rangeBar, similarityLabel } from "../../lib/vendorHistory.ts";

const MAX_LISTED = 8;

function InvoiceRow({ entry, current }: { entry: IndexEntry; current: boolean }) {
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-sm text-fg">{entry.invoice_number ?? entry.filename}</span>
          {current && <Badge tone="accent">This invoice</Badge>}
          {entry.needs_review && <Badge tone="warning">Review</Badge>}
        </span>
        <span className="block truncate text-xs text-fg-subtle tabular-nums">
          {formatDate(entry.invoice_date)}
          {entry.vendor ? ` · ${entry.vendor}` : ""}
        </span>
      </span>
      <span className="shrink-0 text-sm text-fg tabular-nums">{formatMoney(entry.total_amount, entry.currency)}</span>
    </>
  );
  if (current) {
    return <li className="flex items-center gap-3 rounded-lg bg-accent-soft/50 px-2.5 py-2 pr-9">{body}</li>;
  }
  return (
    <li>
      <Link
        to={`/documents/${entry.document_id}`}
        className="group flex items-center gap-3 rounded-lg px-2.5 py-2 transition-colors hover:bg-surface-2"
      >
        {body}
        <ChevronRight className="size-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
      </Link>
    </li>
  );
}

function RangeFigure({ history }: { history: VendorHistory }) {
  const { stats, target } = history;
  const bar = target ? rangeBar(stats, target.total_base) : null;
  const sentence = target ? positionSentence(target) : null;
  const money = (value: string | null) => formatMoney(value, history.base_currency);
  if (!target || !bar || !sentence) return null;
  return (
    <figure className="mt-4">
      <div className="relative h-8" role="img" aria-label={`This invoice: ${money(target.total_base)}, ${sentence}.`}>
        <div className="absolute inset-x-0 top-3.5 h-1 rounded-full bg-border-strong" />
        <div
          className="absolute top-2.5 h-3 rounded-full bg-accent-soft ring-1 ring-accent/30"
          style={{ left: `${bar.bandStart}%`, width: `${Math.max(bar.bandEnd - bar.bandStart, 1)}%` }}
        />
        <div className="absolute top-2 h-4 w-0.5 -translate-x-1/2 bg-fg-muted" style={{ left: `${bar.median}%` }} />
        <div
          className="absolute top-1 size-6 -translate-x-1/2 rounded-full border-2 border-surface bg-accent shadow"
          style={{ left: `${bar.marker}%` }}
        />
      </div>
      <figcaption className="mt-1 text-sm text-fg-muted">
        This invoice is <span className="font-medium text-fg tabular-nums">{money(target.total_base)}</span>, {sentence}.
        <span className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-subtle">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm bg-accent-soft ring-1 ring-accent/30" aria-hidden /> Usual range
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-0.5 bg-fg-muted" aria-hidden /> Median
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-accent" aria-hidden /> This invoice
          </span>
        </span>
      </figcaption>
    </figure>
  );
}

function VendorPanel({ history }: { history: VendorHistory }) {
  const { stats } = history;
  const money = (value: string | null) => formatMoney(value, history.base_currency);
  const others = history.invoices.filter((entry) => entry.document_id !== history.document_id);
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">{history.vendor ?? "Unknown vendor"}</h3>
        {history.match_rule && <Badge>{MATCH_RULE_LABEL[history.match_rule]}</Badge>}
      </div>
      {others.length === 0 ? (
        <p className="mt-2 text-sm text-fg-muted">This is the first invoice from this vendor.</p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {[
              ["Other invoices", `${stats.count}`],
              ["Median", money(stats.median)],
              ["Usual range", stats.q1 && stats.q3 ? `${money(stats.q1)} – ${money(stats.q3)}` : EMPTY],
              ["Total", money(stats.sum)],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0 rounded-xl bg-surface-2 px-3 py-2">
                <dt className="text-xs text-fg-muted">{label}</dt>
                <dd className="mt-0.5 text-sm font-semibold text-fg tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          {stats.skipped_currencies.length > 0 && (
            <p className="mt-2 text-xs text-fg-subtle">
              Not in the statistics (no rate in the table): {stats.skipped_currencies.join(", ")}.
            </p>
          )}
          <RangeFigure history={history} />
          {history.duplicates.length > 0 && (
            <div className="mt-4 rounded-xl border border-warning/30 bg-warning-soft p-3">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-fg">
                <Copy className="size-4 text-warning" aria-hidden />
                Same invoice number as
              </p>
              <ul className="mt-1.5 space-y-1">
                {history.duplicates.map((entry) => (
                  <InvoiceRow key={entry.document_id} entry={entry} current={false} />
                ))}
              </ul>
            </div>
          )}
          <h4 className="mt-5 text-xs font-medium tracking-wide text-fg-muted uppercase">
            Invoices from this vendor
          </h4>
          <ul className="mt-1.5 -mx-2.5 space-y-0.5">
            {history.invoices.slice(0, MAX_LISTED).map((entry) => (
              <InvoiceRow key={entry.document_id} entry={entry} current={entry.document_id === history.document_id} />
            ))}
          </ul>
          {history.invoices.length > MAX_LISTED && (
            <p className="mt-1 text-xs text-fg-subtle">
              and {history.invoices.length - MAX_LISTED} more. Ask AI can list them all.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function SimilarRow({ item }: { item: InvoiceHit }) {
  const details = [item.invoice_number ?? item.filename, formatDate(item.invoice_date)].join(" · ");
  return (
    <li>
      <Link
        to={`/documents/${item.document_id}`}
        className="group flex items-center gap-3 rounded-lg px-2.5 py-2 transition-colors hover:bg-surface-2"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">{item.vendor ?? item.filename}</span>
          <span className="block truncate text-xs text-fg-subtle">{details}</span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-sm text-fg tabular-nums">{formatMoney(item.total_amount, item.currency)}</span>
          <span className="block text-xs text-fg-subtle tabular-nums">{similarityLabel(item.similarity)}</span>
        </span>
        <ChevronRight className="size-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
      </Link>
    </li>
  );
}

function SimilarPanel({ similar }: { similar: SimilarInvoices | null | undefined }) {
  return (
    <div className="min-w-0">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-fg">
        <Layers className="size-4 text-fg-subtle" aria-hidden />
        Similar invoices
      </h3>
      {!similar?.available ? (
        <p className="mt-2 text-sm text-fg-muted">Similarity search is unavailable for this document.</p>
      ) : similar.items.length === 0 ? (
        <p className="mt-2 text-sm text-fg-muted">No similar invoices yet.</p>
      ) : (
        <ul className="mt-2 -mx-2.5 space-y-0.5">
          {similar.items.map((item) => (
            <SimilarRow key={item.document_id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** How this invoice compares with the vendor's other invoices (PRD 0010 D11). */
export function VendorHistorySection({ documentId }: { documentId: string }) {
  const history = useVendorHistory(documentId, { enabled: true });
  const similar = useSimilar(documentId, { enabled: true });

  return (
    <Card aria-labelledby="vendor-history">
      <CardHeader
        id="vendor-history"
        icon={<History className="size-4.5" aria-hidden />}
        title="Vendor history"
        description="This invoice next to the vendor's other invoices and the most similar ones. Totals in the base currency."
      />
      <CardBody>
        {history.isPending || similar.isPending ? (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
            <Skeleton className="h-40 rounded-xl lg:col-span-3" />
            <Skeleton className="h-40 rounded-xl lg:col-span-2" />
          </div>
        ) : history.isError ? (
          <ErrorAlert error={history.error} onRetry={() => void history.refetch()} />
        ) : history.data === null ? (
          <p className="text-sm text-fg-muted">
            This document is not indexed yet, so it can't be compared. Reprocess it, or run the back-fill command, to
            add it.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
            <div className="min-w-0 lg:col-span-3">
              <VendorPanel history={history.data} />
            </div>
            <div className="min-w-0 border-border lg:col-span-2 lg:border-l lg:pl-6">
              <SimilarPanel similar={similar.data} />
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

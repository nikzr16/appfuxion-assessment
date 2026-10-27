import { FileSearch } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";

import type { ConfidenceReport, InvoiceData } from "../../api/types.ts";
import { ConfidenceBadge, NotFoundMarker, ShowInTextButton } from "../../components/ConfidenceBadge.tsx";
import { SEVERITY_STYLE } from "../../components/severity.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { cx } from "../../lib/cx.ts";
import { EMPTY, formatDate, formatMoney } from "../../lib/format.ts";
import { targetId, worstSeverity, type IssueIndex } from "../../lib/issues.ts";
import { IssueMarker } from "./IssueMarker.tsx";
import { DOCUMENT_TYPE_LABELS, FIELD_LABELS } from "./labels.ts";

type FieldName = Exclude<keyof InvoiceData, "line_items">;

export type LocateHandler = (span: { start: number; end: number }) => void;

/** The run's confidence report and the "show in text" handler, shared by every field. */
const GuardrailsContext = createContext<{ report: ConfidenceReport | null; onLocate?: LocateHandler }>({
  report: null,
});

interface FieldProps {
  name: FieldName;
  value: ReactNode;
  issues: IssueIndex;
  emphasis?: boolean;
  wide?: boolean;
}

/** One labelled value; outlined and tinted by its worst validation issue (PRD D8). */
function Field({ name, value, issues, emphasis = false, wide = false }: FieldProps) {
  const fieldIssues = issues.forField(name);
  const worst = worstSeverity(fieldIssues);
  const empty = value === EMPTY || value === null || value === "";
  const { report, onLocate } = useContext(GuardrailsContext);
  const confidence = empty ? undefined : report?.fields[name];
  return (
    <div
      id={targetId(name)}
      className={cx(
        "rounded-xl px-3 py-2.5",
        wide && "sm:col-span-2",
        worst && [SEVERITY_STYLE[worst].tint, SEVERITY_STYLE[worst].ring].join(" "),
      )}
    >
      <dt className="text-xs font-medium text-fg-subtle">{FIELD_LABELS[name]}</dt>
      <dd className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className={cx(
            "max-w-full min-w-0 break-words",
            emphasis ? "text-lg font-semibold tabular-nums" : "text-sm",
            empty ? "text-fg-subtle" : "text-fg",
          )}
        >
          {empty ? EMPTY : value}
        </span>
        <IssueMarker issues={fieldIssues} />
        {confidence && (
          <span className="inline-flex shrink-0 items-center gap-0.5">
            <ConfidenceBadge confidence={confidence} compact={confidence.label === "high"} />
            {onLocate && (
              <ShowInTextButton confidence={confidence} fieldLabel={FIELD_LABELS[name] ?? name} onLocate={onLocate} />
            )}
          </span>
        )}
      </dd>
      {confidence?.grounding === "ungrounded" && (
        <dd className="mt-1">
          <NotFoundMarker />
        </dd>
      )}
    </div>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-1 px-3 text-xs font-semibold tracking-wide text-fg-muted uppercase">{title}</h3>
      <dl className="grid grid-cols-1 gap-x-2 sm:grid-cols-2">{children}</dl>
    </div>
  );
}

interface StructuredDataProps {
  data: InvoiceData;
  issues: IssueIndex;
  title?: string;
  description?: string;
  /** Feature 0008: badges per field; `null` shows the "not available" note. */
  confidence?: ConfidenceReport | null;
  /** Shown under the header when there is no confidence (old results). */
  confidenceNote?: string;
  onLocate?: LocateHandler;
}

/** The extracted fields in four groups. Empty values show "—", never a guess. */
export function StructuredData({
  data,
  issues,
  title = "Extracted data",
  description = "Fields read from the document by the AI.",
  confidence = null,
  confidenceNote,
  onLocate,
}: StructuredDataProps) {
  const money = (value: string | null) => formatMoney(value, data.currency);
  const text = (value: string | null) => value ?? EMPTY;
  return (
    <Card aria-labelledby="structured-data-title">
      <CardHeader
        id="structured-data-title"
        icon={<FileSearch className="size-4.5" aria-hidden />}
        title={title}
        description={description}
      />
      {confidenceNote && (
        <p className="mx-5 mt-4 rounded-xl bg-surface-2 px-3 py-2 text-xs text-fg-muted sm:mx-6">{confidenceNote}</p>
      )}
      <GuardrailsContext.Provider value={{ report: confidence, onLocate }}>
        <CardBody className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Group title="Document">
            <Field name="document_type" value={DOCUMENT_TYPE_LABELS[data.document_type]} issues={issues} />
            <Field name="invoice_number" value={text(data.invoice_number)} issues={issues} />
            <Field name="invoice_date" value={formatDate(data.invoice_date)} issues={issues} />
            <Field name="due_date" value={formatDate(data.due_date)} issues={issues} />
            <Field name="payment_terms" value={text(data.payment_terms)} issues={issues} wide />
          </Group>
          <Group title="Amounts">
            <Field name="currency" value={text(data.currency)} issues={issues} />
            <Field name="subtotal" value={money(data.subtotal)} issues={issues} />
            <Field name="tax" value={money(data.tax)} issues={issues} />
            <Field name="total_amount" value={money(data.total_amount)} issues={issues} emphasis />
          </Group>
          <Group title="Vendor">
            <Field name="vendor" value={text(data.vendor)} issues={issues} />
            <Field name="vendor_tax_id" value={text(data.vendor_tax_id)} issues={issues} />
            <Field name="vendor_address" value={text(data.vendor_address)} issues={issues} wide />
          </Group>
          <Group title="Customer">
            <Field name="customer_name" value={text(data.customer_name)} issues={issues} />
            <Field name="customer_address" value={text(data.customer_address)} issues={issues} wide />
          </Group>
        </CardBody>
      </GuardrailsContext.Provider>
    </Card>
  );
}

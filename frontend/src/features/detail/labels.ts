import type { DocumentType, ValidationStatus } from "../../api/types.ts";
import type { Tone } from "../../components/ui/Badge.tsx";
import { parseIssuePath } from "../../lib/issues.ts";

export const FIELD_LABELS: Record<string, string> = {
  document_type: "Document type",
  vendor: "Vendor",
  vendor_address: "Vendor address",
  vendor_tax_id: "Tax / registration no.",
  customer_name: "Customer",
  customer_address: "Customer address",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  due_date: "Due date",
  payment_terms: "Payment terms",
  currency: "Currency",
  subtotal: "Subtotal",
  tax: "Tax",
  total_amount: "Total",
  line_items: "Line items",
};

export const COLUMN_LABELS: Record<string, string> = {
  description: "description",
  quantity: "quantity",
  unit_price: "unit price",
  amount: "amount",
};

/** `line_items[2].amount` → `Line 3 · amount`; `total_amount` → `Total`. */
export function issueLocation(path: string): string {
  const target = parseIssuePath(path);
  if (target.kind === "table") return "Line items";
  if (target.kind === "line") {
    const column = target.column ? ` · ${COLUMN_LABELS[target.column] ?? target.column}` : "";
    return `Line ${target.index + 1}${column}`;
  }
  return FIELD_LABELS[target.field] ?? target.field;
}

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  invoice: "Invoice",
  receipt: "Receipt",
  unknown: "Not a financial document",
};

export const VALIDATION_STATUS: Record<ValidationStatus, { tone: Tone; label: string }> = {
  pass: { tone: "success", label: "Passed" },
  warn: { tone: "warning", label: "Passed with warnings" },
  fail: { tone: "danger", label: "Failed" },
};

/** The backend stores failures as `code: message`; split them for display. */
export function splitError(error: string): { code: string | null; message: string } {
  const match = /^([a-z][a-z0-9_]*): ([\s\S]*)$/.exec(error);
  return match ? { code: match[1] ?? null, message: match[2] ?? error } : { code: null, message: error };
}

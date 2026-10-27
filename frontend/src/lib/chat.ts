/**
 * Ask AI chat helpers (PRD 0010 D11): the stored conversation ID, the document the user is
 * looking at, and readable labels for the Query Agent's tool steps.
 */
import type { ToolStep } from "../api/types.ts";
import { formatDate } from "./format.ts";

export const STORAGE_KEY = "askai.conversation";
export const QUESTION_MAX = 500;
export const QUESTION_MIN = 3;
/** Show the character counter from this length on. */
export const COUNTER_FROM = 400;

/** The open conversation survives reloads in this tab (sessionStorage may be blocked). */
export function readStoredConversation(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeConversation(id: string | null): void {
  try {
    if (id === null) window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage unavailable: the chat still works, it just is not restored after a reload.
  }
}

const DOCUMENT_PATH = /^\/documents\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i;

/** The document ID when the current page is a document's detail page. */
export function documentIdFromPath(pathname: string): string | undefined {
  return DOCUMENT_PATH.exec(pathname)?.[1]?.toLowerCase();
}

export function canAsk(question: string): boolean {
  const length = question.trim().length;
  return length >= QUESTION_MIN && length <= QUESTION_MAX;
}

const TOOL_TITLE: Record<string, string> = {
  search_invoices: "Searched the invoices",
  get_vendor_history: "Looked up the vendor's history",
  submit_answer: "Wrote the answer",
};

const ARGUMENT_LABEL: Record<string, string> = {
  text: "text",
  vendor: "vendor",
  invoice_number: "invoice",
  currency: "currency",
  document_type: "type",
  document_id: "document",
};

function describeArguments(args: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, label] of Object.entries(ARGUMENT_LABEL)) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) {
      parts.push(`${label} “${key === "document_id" ? value.slice(0, 8) : value}”`);
    }
  }
  const from = typeof args.date_from === "string" ? args.date_from : null;
  const to = typeof args.date_to === "string" ? args.date_to : null;
  if (from && to) parts.push(`${formatDate(from)} to ${formatDate(to)}`);
  else if (from) parts.push(`from ${formatDate(from)}`);
  else if (to) parts.push(`until ${formatDate(to)}`);
  if (typeof args.min_total === "number") parts.push(`total ≥ ${args.min_total}`);
  if (typeof args.max_total === "number") parts.push(`total ≤ ${args.max_total}`);
  return parts.join(", ");
}

const ERROR_TEXT: Record<string, string> = {
  numbers_not_found: "Was asked to copy numbers exactly from the data",
  vendor_not_found: "No vendor with that name",
  not_indexed: "That document is not indexed yet",
  invalid_arguments: "Asked the tool in the wrong way and tried again",
};

export interface StepLine {
  title: string;
  detail: string;
  failed: boolean;
}

/** One readable line per tool step for "How I found this". */
export function describeStep(step: ToolStep): StepLine {
  const title = TOOL_TITLE[step.tool] ?? step.tool.replace(/_/g, " ");
  if (step.error) {
    return { title, detail: ERROR_TEXT[step.error.code] ?? step.error.message, failed: true };
  }
  let detail = step.tool === "submit_answer" ? "" : describeArguments(step.arguments);
  const result = step.result ?? {};
  if (step.tool === "search_invoices" && typeof result.total_matches === "number") {
    const count = result.total_matches;
    detail = [detail, `${count} match${count === 1 ? "" : "es"}`].filter(Boolean).join(" · ");
  }
  if (step.tool === "get_vendor_history" && Array.isArray(result.invoices)) {
    const count = result.invoices.length;
    detail = [detail, `${count} invoice${count === 1 ? "" : "s"}`].filter(Boolean).join(" · ");
  }
  return { title, detail, failed: false };
}

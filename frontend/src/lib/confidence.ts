/**
 * Guardrails view helpers (feature 0008, PRD D9): how a confidence label looks, which field
 * of a report belongs to a value on screen, and where a value sits in the raw text.
 */
import type { ConfidenceLabel, ConfidenceReport, FieldConfidence, GroundingStatus } from "../api/types.ts";

/** A span of `raw_text` to highlight; `nonce` makes a repeated click scroll again. */
export interface TextHighlight {
  start: number;
  end: number;
  nonce: number;
}

export const CONFIDENCE_LABEL: Record<ConfidenceLabel, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const GROUNDING_LABEL: Record<GroundingStatus, string> = {
  grounded: "Found in the document",
  weak: "Close match in the document",
  inferred: "Inferred from a printed symbol",
  ungrounded: "Not found in the document",
  skipped: "Not a printed value",
};

/** `0.917` → `92%` */
export function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function lineItemPath(index: number, column: string): string {
  return `line_items[${index}].${column}`;
}

export function confidenceOf(
  report: ConfidenceReport | null | undefined,
  path: string,
): FieldConfidence | undefined {
  return report?.fields[path];
}

/** The span to highlight, or `null` when the value was not found in the text. */
export function highlightOf(field: FieldConfidence | undefined): Omit<TextHighlight, "nonce"> | null {
  if (!field || field.start === null || field.end === null || field.end <= field.start) return null;
  return { start: field.start, end: field.end };
}

/** One tooltip line per reason, led by the label and score. */
export function confidenceTooltip(field: FieldConfidence): string {
  return [`${CONFIDENCE_LABEL[field.label]} confidence (${formatScore(field.score)})`, ...field.reasons].join(
    "\n",
  );
}

/** Splits `text` around a highlight so it can be rendered as before / match / after. */
export function splitAt(text: string, highlight: Pick<TextHighlight, "start" | "end"> | null) {
  if (!highlight) return null;
  const start = Math.max(0, Math.min(highlight.start, text.length));
  const end = Math.max(start, Math.min(highlight.end, text.length));
  if (end === start) return null;
  return { before: text.slice(0, start), match: text.slice(start, end), after: text.slice(end) };
}

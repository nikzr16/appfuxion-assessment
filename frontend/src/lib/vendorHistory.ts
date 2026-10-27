/**
 * Vendor history display helpers (PRD 0010 D11): where one invoice sits among the vendor's
 * other invoices. All numbers come from the backend; this only maps them onto a 0-100 % bar.
 */
import type { HistoryStats, MatchRule, TargetPosition } from "../api/types.ts";
import { formatDecimal } from "./format.ts";

export const MATCH_RULE_LABEL: Record<MatchRule, string> = {
  tax_id: "Matched by tax ID",
  name: "Matched by name",
};

export interface RangeBar {
  /** Left and right edge of the usual range (Q1–Q3), in % of the bar. */
  bandStart: number;
  bandEnd: number;
  median: number;
  /** This invoice's total, in % of the bar. */
  marker: number;
}

const clamp = (value: number) => Math.min(100, Math.max(0, value));

/**
 * Positions for a min–max bar that also fits this invoice. `null` without enough data
 * (no statistics, no converted total, or every value equal).
 */
export function rangeBar(stats: HistoryStats, total: string | null): RangeBar | null {
  const values = [stats.min, stats.max, stats.q1, stats.q3, stats.median, total];
  if (values.some((value) => value === null)) return null;
  const [min, max, q1, q3, median, own] = values.map(Number) as [number, number, number, number, number, number];
  const low = Math.min(min, own);
  const high = Math.max(max, own);
  if (!(high > low)) return null;
  const at = (value: number) => clamp(((value - low) / (high - low)) * 100);
  return { bandStart: at(q1), bandEnd: at(q3), median: at(median), marker: at(own) };
}

const POSITION_TEXT: Record<NonNullable<TargetPosition["position"]>, string> = {
  below: "below the usual range",
  within: "within the usual range",
  above: "above the usual range",
};

/** "12.5% above the median, within the usual range" (numbers as the backend gave them). */
export function positionSentence(target: TargetPosition): string | null {
  if (target.diff_pct === null || target.position === null) return null;
  const pct = Number(target.diff_pct);
  const relation =
    pct === 0
      ? "equal to the median"
      : `${formatDecimal(target.diff_pct.replace("-", ""))}% ${pct > 0 ? "above" : "below"} the median`;
  return `${relation}, ${POSITION_TEXT[target.position]}`;
}

/** "92% similar" from a 0–1 cosine similarity. */
export function similarityLabel(similarity: number | null): string {
  if (similarity === null) return "Exact match";
  return `${Math.round(similarity * 100)}% similar`;
}

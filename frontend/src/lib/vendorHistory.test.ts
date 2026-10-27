import { describe, expect, it } from "vitest";

import type { HistoryStats, TargetPosition } from "../api/types.ts";
import { positionSentence, rangeBar, similarityLabel } from "./vendorHistory.ts";

const STATS: HistoryStats = {
  base_currency: "MYR",
  count: 5,
  with_total: 5,
  skipped_currencies: [],
  sum: "1500.00",
  min: "100.00",
  max: "500.00",
  mean: "300.00",
  median: "300.00",
  q1: "200.00",
  q3: "400.00",
  low_fence: "-100.00",
  high_fence: "700.00",
};

const TARGET: TargetPosition = {
  document_id: "d",
  total_base: "900.00",
  diff_vs_median: "600.00",
  diff_pct: "200.0",
  rank: 1,
  position: "above",
};

describe("vendor history helpers", () => {
  it("places the usual range, the median and this invoice on one bar", () => {
    expect(rangeBar(STATS, "900.00")).toEqual({ bandStart: 12.5, bandEnd: 37.5, median: 25, marker: 100 });
    expect(rangeBar(STATS, "300.00")).toEqual({ bandStart: 25, bandEnd: 75, median: 50, marker: 50 });
  });

  it("has no bar without statistics, a total or a spread", () => {
    expect(rangeBar({ ...STATS, median: null }, "1")).toBeNull();
    expect(rangeBar(STATS, null)).toBeNull();
    const flat = { ...STATS, min: "5", max: "5", q1: "5", q3: "5", median: "5" };
    expect(rangeBar(flat, "5")).toBeNull();
  });

  it("says where the invoice sits", () => {
    expect(positionSentence(TARGET)).toBe("200.0% above the median, above the usual range");
    expect(positionSentence({ ...TARGET, diff_pct: "-12.5", position: "within" })).toBe(
      "12.5% below the median, within the usual range",
    );
    expect(positionSentence({ ...TARGET, diff_pct: "0.0", position: "within" })).toBe(
      "equal to the median, within the usual range",
    );
    expect(positionSentence({ ...TARGET, diff_pct: null })).toBeNull();
  });

  it("labels similarity", () => {
    expect(similarityLabel(0.9234)).toBe("92% similar");
    expect(similarityLabel(null)).toBe("Exact match");
  });
});

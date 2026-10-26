import { describe, expect, it } from "vitest";

import {
  costMicros,
  fileKind,
  formatAmount,
  formatBytes,
  formatCost,
  formatDate,
  formatDecimal,
  formatDuration,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatRelative,
  formatTimestamp,
  formatTokens,
  microsToCost,
  minorUnits,
} from "./format.ts";

describe("money", () => {
  it.each([
    ["1234.5", "MYR", "MYR 1,234.50"],
    ["1200", "JPY", "JPY 1,200"],
    ["12.5", "KWD", "KWD 12.500"],
    ["1234567.891", "MYR", "MYR 1,234,567.891"],
    ["-12", "MYR", "MYR -12.00"],
    ["0.1", "USD", "USD 0.10"],
    ["1095.00", null, "1,095.00"],
  ])("formatMoney(%s, %s) = %s", (value, currency, expected) => {
    expect(formatMoney(value, currency)).toBe(expected);
  });

  it("keeps extra printed precision instead of rounding", () => {
    expect(formatAmount("12.3456", "MYR")).toBe("12.3456");
  });

  it("never goes through floating point", () => {
    // 0.1 + 0.2 style values and huge numbers stay exact.
    expect(formatAmount("90071992547409931.37", "MYR")).toBe("90,071,992,547,409,931.37");
  });

  it("shows a dash for missing values and non-decimals as printed", () => {
    expect(formatMoney(null, "MYR")).toBe("—");
    expect(formatMoney("", "MYR")).toBe("—");
    expect(formatMoney("1E+3", "MYR")).toBe("MYR 1E+3");
  });

  it("uses 2 minor units for unknown or missing currencies", () => {
    expect(minorUnits(null)).toBe(2);
    expect(minorUnits("ZZZ")).toBe(2);
    expect(minorUnits("JPY")).toBe(0);
  });

  it("groups quantities without padding", () => {
    expect(formatQuantity("1500")).toBe("1,500");
    expect(formatQuantity("2.5")).toBe("2.5");
    expect(formatQuantity(null)).toBe("—");
    expect(formatDecimal("7", 2)).toBe("7.00");
  });
});

describe("dates", () => {
  it("shows ISO dates as DD-MM-YYYY without time-zone shifts", () => {
    expect(formatDate("2025-03-04")).toBe("04-03-2025");
    expect(formatDate("2026-12-31")).toBe("31-12-2026");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("soon")).toBe("soon");
  });

  it("shows timestamps as DD-MM-YYYY HH:mm in local time", () => {
    const local = new Date(2026, 9, 27, 9, 5);
    expect(formatTimestamp(local.toISOString())).toBe("27-10-2026 09:05");
    expect(formatTimestamp(null)).toBe("—");
  });

  it("describes relative time", () => {
    const now = Date.parse("2026-10-27T10:00:00Z");
    expect(formatRelative("2026-10-27T09:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-10-27T09:57:00Z", now)).toBe("3 minutes ago");
    expect(formatRelative("2026-10-26T10:00:00Z", now)).toBe("yesterday");
  });
});

describe("sizes and durations", () => {
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(2.4 * 1024 * 1024)).toBe("2.4 MB");
  });

  it("formats durations", () => {
    expect(formatDuration(850)).toBe("850 ms");
    expect(formatDuration(3200)).toBe("3.2 s");
    expect(formatDuration(65_000)).toBe("1 min 5 s");
    expect(formatDuration(120_000)).toBe("2 min");
  });

  it("names file kinds", () => {
    expect(fileKind("application/pdf")).toBe("PDF");
    expect(fileKind("image/jpeg")).toBe("JPG");
    expect(fileKind("image/webp")).toBe("WEBP");
  });
});

describe("formatTokens", () => {
  it("groups small counts and shortens large ones", () => {
    expect(formatTokens(842)).toBe("842");
    expect(formatTokens(9120)).toBe("9,120");
    expect(formatTokens(12_340)).toBe("12.3k");
    expect(formatTokens(40_000)).toBe("40k");
    expect(formatTokens(1_250_000)).toBe("1.3M");
  });
});

describe("costs", () => {
  it("converts decimal strings to micro-dollars exactly and back", () => {
    expect(costMicros("0.001440")).toBe(1440);
    expect(costMicros("1.5")).toBe(1_500_000);
    expect(microsToCost(1440 + 240)).toBe("0.001680");
    expect(microsToCost(2_000_001)).toBe("2.000001");
  });

  it("formats estimates with sensible precision", () => {
    expect(formatCost(null)).toBe("—");
    expect(formatCost("0.000000")).toBe("$0.00");
    expect(formatCost("0.000040")).toBe("<$0.0001");
    expect(formatCost("0.001440")).toBe("$0.0014");
    expect(formatCost("0.042000")).toBe("$0.042");
    expect(formatCost("1.240000")).toBe("$1.24");
  });
});

describe("formatPercent", () => {
  it("shows whole percentages without decimals", () => {
    expect(formatPercent(0.8)).toBe("80%");
    expect(formatPercent(0.995)).toBe("99.5%");
    expect(formatPercent(null)).toBe("—");
  });
});

import { describe, expect, it } from "vitest";

import { makeConfidence } from "../test/fixtures.ts";
import {
  confidenceOf,
  confidenceTooltip,
  formatScore,
  highlightOf,
  lineItemPath,
  splitAt,
} from "./confidence.ts";

describe("confidence helpers", () => {
  it("formats a score as a whole percent", () => {
    expect(formatScore(0.917)).toBe("92%");
    expect(formatScore(1)).toBe("100%");
    expect(formatScore(0)).toBe("0%");
  });

  it("finds a field by path, including line-item cells", () => {
    const report = makeConfidence();
    expect(confidenceOf(report, "vendor")?.grounding).toBe("ungrounded");
    expect(confidenceOf(report, lineItemPath(0, "amount"))?.label).toBe("high");
    expect(confidenceOf(null, "vendor")).toBeUndefined();
    expect(confidenceOf(report, "due_date")).toBeUndefined();
  });

  it("only highlights values that were found", () => {
    const report = makeConfidence();
    expect(highlightOf(report.fields.invoice_number)).toEqual({ start: 8, end: 16 });
    expect(highlightOf(report.fields.vendor)).toBeNull();
    expect(highlightOf(undefined)).toBeNull();
  });

  it("builds a tooltip with the label, score and reasons", () => {
    expect(confidenceTooltip(makeConfidence().fields.currency!)).toBe(
      "High confidence (90%)\nInferred from the printed symbol 'RM' on page 1",
    );
  });

  it("splits text around a highlight and clamps it to the text", () => {
    expect(splitAt("INVOICE BL-88731", { start: 8, end: 16 })).toEqual({
      before: "INVOICE ",
      match: "BL-88731",
      after: "",
    });
    expect(splitAt("short", { start: 2, end: 99 })).toEqual({ before: "sh", match: "ort", after: "" });
    expect(splitAt("short", { start: 9, end: 12 })).toBeNull();
    expect(splitAt("short", null)).toBeNull();
  });
});

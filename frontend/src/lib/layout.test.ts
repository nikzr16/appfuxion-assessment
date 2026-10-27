import { describe, expect, it } from "vitest";

import { makeConfidence, makeLayout } from "../test/fixtures.ts";
import { blockCounts, boxStyle, columnTitles, lineItemLocation, pageAspect, pagesLabel } from "./layout.ts";

describe("layout helpers", () => {
  it("turns a 0-1 box into percentages, clamped to the page", () => {
    expect(boxStyle([0.1, 0.25, 0.6, 0.3])).toEqual({ left: "10.00%", top: "25.00%", width: "50.00%", height: "5.00%" });
    expect(boxStyle([-0.1, 0, 1.2, 1])).toEqual({ left: "0.00%", top: "0.00%", width: "100.00%", height: "100.00%" });
  });

  it("names pages", () => {
    expect(pagesLabel([2])).toBe("Page 2");
    expect(pagesLabel([1, 2, 3])).toBe("Pages 1–3");
    expect(pagesLabel([])).toBe("");
  });

  it("uses the printed titles, else the column roles", () => {
    const [table] = makeLayout().tables;
    expect(columnTitles(table!)).toEqual(["Description", "Qty", "Unit Price", "Amount"]);
    expect(columnTitles({ ...table!, header: null, columns: ["description", "other"] })).toEqual([
      "Description",
      "Column 2",
    ]);
  });

  it("finds a table-derived line item's row on the page", () => {
    const report = makeConfidence();
    report.fields["line_items[1].description"] = {
      ...report.fields["line_items[0].amount"]!,
      path: "line_items[1].description",
      location: { page: 1, box: [0.1, 0.36, 0.4, 0.39], block: "line_items", table: 0, row: 1, column: "description" },
    };
    const layout = makeLayout();

    // The whole row's box from the layout wins over the cell's own box.
    expect(lineItemLocation(report, layout, 1)).toEqual({ page: 1, box: [0.08, 0.36, 0.92, 0.39] });
    // Without the layout the cell box is used; items the model read have no location.
    expect(lineItemLocation(report, undefined, 1)).toEqual({ page: 1, box: [0.1, 0.36, 0.4, 0.39] });
    expect(lineItemLocation(report, layout, 0)).toBeNull();
    expect(lineItemLocation(null, layout, 1)).toBeNull();
  });

  it("counts blocks by type in reading order", () => {
    const layout = makeLayout();
    expect(blockCounts(layout).map((c) => c.type)).toEqual(["header", "document_info", "line_items", "totals"]);
    expect(blockCounts(layout, 2)).toEqual([]);
  });

  it("knows each page's shape", () => {
    expect(pageAspect(makeLayout(), 1)).toBeCloseTo(595 / 842);
    expect(pageAspect(makeLayout({ pages: [] }), 3)).toBeCloseTo(595 / 842);
  });
});

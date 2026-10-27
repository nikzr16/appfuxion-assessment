import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { IndexEntry, SimilarInvoices, VendorHistory } from "../../api/types.ts";
import { apiError, mockApi, ok } from "../../test/fetchMock.ts";
import { DOC_ID, makeDocument, makeResult, makeRun, makeTrace } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const PATH = `/documents/${DOC_ID}`;
const EARLIER = "11111111-2222-4333-8444-555555555555";

function entry(overrides: Partial<IndexEntry> = {}): IndexEntry {
  return {
    document_id: EARLIER,
    filename: "abc-1.pdf",
    uploaded_at: "2026-10-01T10:00:00+08:00",
    run_id: null,
    document_type: "invoice",
    vendor: "ABC Supplies",
    vendor_tax_id: null,
    invoice_number: "INV-1",
    invoice_date: "2026-09-02",
    currency: "MYR",
    total_amount: "300.00",
    total_base: "300.00",
    base_currency: "MYR",
    needs_review: false,
    embedded: true,
    ...overrides,
  };
}

function history(overrides: Partial<VendorHistory> = {}): VendorHistory {
  return {
    document_id: DOC_ID,
    vendor: "ABC Supplies",
    match_rule: "tax_id",
    base_currency: "MYR",
    invoices: [
      entry({ document_id: DOC_ID, invoice_number: "INV-9", total_amount: "900.00", total_base: "900.00" }),
      entry(),
    ],
    earlier: 5,
    later: 0,
    stats: {
      base_currency: "MYR",
      count: 5,
      with_total: 5,
      skipped_currencies: ["XAU"],
      sum: "1500.00",
      min: "100.00",
      max: "500.00",
      mean: "300.00",
      median: "300.00",
      q1: "200.00",
      q3: "400.00",
      low_fence: "-100.00",
      high_fence: "700.00",
    },
    target: {
      document_id: DOC_ID,
      total_base: "900.00",
      diff_vs_median: "600.00",
      diff_pct: "200.0",
      rank: 1,
      position: "above",
    },
    duplicates: [entry()],
    ...overrides,
  };
}

const SIMILAR: SimilarInvoices = {
  document_id: DOC_ID,
  available: true,
  items: [{ ...entry({ invoice_number: "INV-7" }), similarity: 0.934 }],
};

function routes(extra: Record<string, ReturnType<typeof ok>>) {
  return {
    "GET /health": ok({ status: "ok", database: "ok" }),
    [`GET /documents/${DOC_ID}`]: ok(makeDocument()),
    [`GET /documents/${DOC_ID}/result`]: ok(makeResult()),
    [`GET /documents/${DOC_ID}/runs`]: ok([makeRun()]),
    [`GET /documents/${DOC_ID}/trace`]: ok(makeTrace()),
    ...extra,
  };
}

describe("Vendor history section (feature 0010)", () => {
  it("shows the vendor's statistics, this invoice's position, duplicates and similar invoices", async () => {
    mockApi(
      routes({
        [`GET /documents/${DOC_ID}/vendor-history`]: ok(history()),
        [`GET /documents/${DOC_ID}/similar`]: ok(SIMILAR),
      }),
    );
    renderApp(PATH);

    const section = await screen.findByRole("region", { name: "Vendor history" });
    expect(await within(section).findByText("Matched by tax ID")).toBeInTheDocument();
    const median = within(section).getByText("Median", { selector: "dt" }).nextElementSibling;
    expect(median).toHaveTextContent("MYR 300.00");
    expect(within(section).getByText("MYR 200.00 – MYR 400.00")).toBeInTheDocument();
    expect(within(section).getByText(/200.0% above the median, above the usual range/)).toBeInTheDocument();
    expect(
      within(section).getByRole("img", { name: "This invoice: MYR 900.00, 200.0% above the median, above the usual range." }),
    ).toBeInTheDocument();
    expect(within(section).getByText(/no rate in the table\): XAU/)).toBeInTheDocument();
    expect(within(section).getByText("Same invoice number as")).toBeInTheDocument();
    expect(within(section).getByText("This invoice", { selector: "span.rounded-full" })).toBeInTheDocument();
    const links = within(section).getAllByRole("link", { name: /INV-1/ });
    expect(links[0]).toHaveAttribute("href", `/documents/${EARLIER}`);
    expect(within(section).getByText("93% similar")).toBeInTheDocument();
    expect(within(section).getByText("INV-7 · 02-09-2026")).toBeInTheDocument();
  });

  it("says when this is the vendor's first invoice", async () => {
    mockApi(
      routes({
        [`GET /documents/${DOC_ID}/vendor-history`]: ok(
          history({ invoices: [entry({ document_id: DOC_ID })], duplicates: [], target: null, match_rule: null }),
        ),
        [`GET /documents/${DOC_ID}/similar`]: ok({ document_id: DOC_ID, available: true, items: [] }),
      }),
    );
    renderApp(PATH);

    const section = await screen.findByRole("region", { name: "Vendor history" });
    expect(await within(section).findByText("This is the first invoice from this vendor.")).toBeInTheDocument();
    expect(within(section).getByText("No similar invoices yet.")).toBeInTheDocument();
  });

  it("explains a document that is not indexed yet", async () => {
    mockApi(
      routes({
        [`GET /documents/${DOC_ID}/vendor-history`]: apiError(409, "not_indexed"),
        [`GET /documents/${DOC_ID}/similar`]: apiError(409, "not_indexed"),
      }),
    );
    renderApp(PATH);

    const section = await screen.findByRole("region", { name: "Vendor history" });
    expect(await within(section).findByText(/not indexed yet/)).toBeInTheDocument();
  });
});

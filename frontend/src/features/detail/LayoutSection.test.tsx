import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LayoutResponse } from "../../api/types.ts";
import { apiError, mockApi, ok } from "../../test/fetchMock.ts";
import {
  DOC_ID,
  makeConfidence,
  makeDocument,
  makeInvoice,
  makeLayout,
  makeResult,
  makeRun,
  makeTrace,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const PATH = `/documents/${DOC_ID}`;

function routes(layout: ReturnType<typeof ok> = ok(makeLayout()), extra: Record<string, ReturnType<typeof ok>> = {}) {
  return {
    "GET /health": ok({ status: "ok", database: "ok" }),
    [`GET /documents/${DOC_ID}`]: ok(makeDocument()),
    [`GET /documents/${DOC_ID}/result`]: ok(makeResult()),
    [`GET /documents/${DOC_ID}/runs`]: ok([makeRun()]),
    [`GET /documents/${DOC_ID}/trace`]: ok(makeTrace()),
    [`GET /documents/${DOC_ID}/layout`]: layout,
    ...extra,
  };
}

async function openLayout() {
  return screen.findByRole("region", { name: "Tables & layout" });
}

describe("Tables & layout section (feature 0009)", () => {
  it("shows the tables the analysis found", async () => {
    mockApi(routes());
    renderApp(PATH);

    const section = await openLayout();
    expect(await within(section).findByText("1 table · 4 blocks · 1 page")).toBeInTheDocument();
    expect(within(section).getByText("Found in the PDF by code (no AI)")).toBeInTheDocument();
    expect(within(section).getByText("Line-item table")).toBeInTheDocument();
    const table = within(section).getByRole("table", { name: "Table 1" });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Description",
      "Qty",
      "Unit Price",
      "Amount",
    ]);
    expect(within(table).getByRole("cell", { name: "Pallet storage" })).toBeInTheDocument();
  });

  it("draws numbered, labelled blocks over the page image", async () => {
    mockApi(routes());
    renderApp(PATH);
    const section = await openLayout();
    await within(section).findByText("1 table · 4 blocks · 1 page");

    await userEvent.click(within(section).getByRole("tab", { name: "Page" }));
    const image = within(section).getByRole("img", { name: "Page 1 of the document" });
    expect(image).toHaveAttribute("src", `/api/documents/${DOC_ID}/pages/1/image`);
    fireEvent.load(image);

    const legend = within(section).getByRole("list", { name: "Block types on this page" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Vendor",
      "Document info",
      "Line items",
      "Totals",
    ]);
    const blocks = within(section).getByRole("list", { name: "Blocks in reading order" });
    expect(within(blocks).getAllByRole("listitem")).toHaveLength(4);
    expect(within(blocks).getByText("Total RM 1,182.60")).toBeInTheDocument();
    expect(within(section).getByText(/numbered in reading order/)).toBeInTheDocument();
  });

  it("lists a scan's blocks without boxes", async () => {
    const scan: LayoutResponse = makeLayout({
      source: "vision",
      layout_version: "vision.v1",
      blocks: makeLayout().blocks.map((block) => ({ ...block, box: null })),
      tables: makeLayout().tables.map((table) => ({ ...table, strategy: "vision", box: null })),
    });
    mockApi(routes(ok(scan)));
    renderApp(PATH);
    const section = await openLayout();

    expect(await within(section).findByText("Hint for the model")).toBeInTheDocument();
    expect(within(section).getByText("Read from the page images by the vision model")).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("tab", { name: "Page" }));
    expect(within(section).getByText(/Scanned pages have no positions/)).toBeInTheDocument();
  });

  it("asks to reprocess when the document has no layout yet", async () => {
    mockApi(routes(apiError(409, "layout_unavailable")));
    renderApp(PATH);
    const section = await openLayout();

    expect(await within(section).findByText(/Layout not analysed — reprocess the document/)).toBeInTheDocument();
    expect(within(section).queryByRole("tab")).not.toBeInTheDocument();
  });

  it("shows a table line on the page from the line items", async () => {
    const confidence = makeConfidence();
    confidence.fields["line_items[1].description"] = {
      ...confidence.fields["line_items[0].amount"]!,
      path: "line_items[1].description",
      location: { page: 1, box: [0.1, 0.36, 0.4, 0.39], block: "line_items", table: 0, row: 1, column: "description" },
    };
    mockApi(
      routes(ok(makeLayout()), {
        [`GET /documents/${DOC_ID}/result`]: ok(makeResult({ confidence })),
        [`GET /documents/${DOC_ID}/extraction`]: ok({
          document_id: DOC_ID,
          structured_data: makeInvoice(),
          model: "gpt-4.1-mini",
          prompt_version: "structured_extraction.v3",
          attempts: 1,
          line_items_source: "table",
        }),
      }),
    );
    renderApp(PATH);

    const lineItems = await screen.findByRole("region", { name: "Line items" });
    expect(await within(lineItems).findByText("Copied from the table")).toBeInTheDocument();
    const show = await within(lineItems).findByRole("button", { name: "Show line 2 on page 1" });
    expect(within(lineItems).queryByRole("button", { name: /Show line 1 on page/ })).not.toBeInTheDocument();

    await userEvent.click(show);
    const section = await openLayout();
    expect(within(section).getByRole("tab", { name: "Page" })).toHaveAttribute("aria-selected", "true");
    fireEvent.load(within(section).getByRole("img", { name: "Page 1 of the document" }));
    expect(within(section).getByRole("img", { name: "Highlighted: line 2" })).toHaveStyle({ top: "35.70%" });
  });
});

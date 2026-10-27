/**
 * Tables-and-layout view helpers (feature 0009, PRD D11): how a block type looks, where a
 * box sits on the page preview, and which row a "Show on page" click points at.
 */
import {
  Banknote,
  Building2,
  FileText,
  LayoutList,
  ReceiptText,
  Sigma,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import type {
  BlockType,
  Box,
  ColumnRole,
  ConfidenceReport,
  LayoutResponse,
  LayoutTable,
  TableStrategy,
} from "../api/types.ts";

/** A row (or block) to highlight on the page preview; `nonce` makes a repeated click scroll again. */
export interface PageHighlight {
  page: number;
  box: Box;
  label: string;
  nonce: number;
}

export interface BlockMeta {
  label: string;
  Icon: LucideIcon;
  /** Tailwind classes for the box outline / swatch in the block's categorical colour. */
  border: string;
  swatch: string;
}

/** In reading order; the colours are the validated `--block-*` tokens (index.css). */
export const BLOCK_ORDER: readonly BlockType[] = [
  "header",
  "document_info",
  "bill_to",
  "line_items",
  "totals",
  "payment",
  "other",
];

export const BLOCK_META: Record<BlockType, BlockMeta> = {
  header: { label: "Vendor", Icon: Building2, border: "border-block-header", swatch: "bg-block-header" },
  document_info: {
    label: "Document info",
    Icon: FileText,
    border: "border-block-document-info",
    swatch: "bg-block-document-info",
  },
  bill_to: { label: "Bill to", Icon: UserRound, border: "border-block-bill-to", swatch: "bg-block-bill-to" },
  line_items: {
    label: "Line items",
    Icon: LayoutList,
    border: "border-block-line-items",
    swatch: "bg-block-line-items",
  },
  totals: { label: "Totals", Icon: Sigma, border: "border-block-totals", swatch: "bg-block-totals" },
  payment: { label: "Payment", Icon: Banknote, border: "border-block-payment", swatch: "bg-block-payment" },
  other: { label: "Other", Icon: ReceiptText, border: "border-block-other", swatch: "bg-block-other" },
};

export const COLUMN_ROLE_LABEL: Record<ColumnRole, string> = {
  description: "Description",
  quantity: "Qty",
  unit_price: "Unit price",
  amount: "Amount",
  other: "Other",
};

export const STRATEGY_LABEL: Record<TableStrategy, string> = {
  lines: "Ruled table",
  text: "Aligned columns",
  vision: "Read by the vision model",
};

/** Room around a block's text so its outline never touches the letters (fraction of the page). */
export const BLOCK_PAD = 0.006;

/** A 0-1 box (optionally grown by `pad`) as absolute-position percentages over the page image. */
export function boxStyle(box: Box, pad = 0): { left: string; top: string; width: string; height: string } {
  const padded: Box = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad];
  const [x0, y0, x1, y1] = padded.map((value) => Math.min(Math.max(value, 0), 1)) as Box;
  const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
  return { left: pct(x0), top: pct(y0), width: pct(Math.max(x1 - x0, 0)), height: pct(Math.max(y1 - y0, 0)) };
}

/** `[1]` → `Page 1`; `[1, 2, 3]` → `Pages 1–3`. */
export function pagesLabel(pages: readonly number[]): string {
  if (pages.length === 0) return "";
  const first = pages[0];
  const last = pages[pages.length - 1];
  return first === last ? `Page ${first}` : `Pages ${first}–${last}`;
}

/** The table's column titles, or its roles when it has no title row. */
export function columnTitles(table: LayoutTable): string[] {
  return table.columns.map((role, index) => table.header?.[index] ?? (role === "other" ? `Column ${index + 1}` : COLUMN_ROLE_LABEL[role]));
}

export function isNumericColumn(role: ColumnRole): boolean {
  return role === "quantity" || role === "unit_price" || role === "amount";
}

/**
 * The page and box of line item `index` when code copied it from a table: the whole row's
 * box from the layout when known, else the cell's own box from the grounding location.
 */
export function lineItemLocation(
  report: ConfidenceReport | null | undefined,
  layout: LayoutResponse | null | undefined,
  index: number,
): { page: number; box: Box } | null {
  if (!report) return null;
  for (const column of ["description", "amount", "unit_price", "quantity"]) {
    const location = report.fields[`line_items[${index}].${column}`]?.location;
    if (!location || location.table === null || location.row === null) continue;
    const row = layout?.tables[location.table]?.rows[location.row];
    const box = row?.box ?? location.box;
    if (box) return { page: row?.page ?? location.page, box };
  }
  return null;
}

/** Block counts by type, in reading order (for the legend). */
export function blockCounts(layout: LayoutResponse, page?: number): { type: BlockType; count: number }[] {
  const counts = new Map<BlockType, number>();
  for (const block of layout.blocks) {
    if (page !== undefined && block.page !== page) continue;
    counts.set(block.type, (counts.get(block.type) ?? 0) + 1);
  }
  return BLOCK_ORDER.filter((type) => counts.has(type)).map((type) => ({ type, count: counts.get(type) ?? 0 }));
}

/** Width / height of page `page` (falls back to the first known page, then A4). */
export function pageAspect(layout: LayoutResponse, page: number): number {
  const info = layout.pages.find((p) => p.page === page) ?? layout.pages[0];
  return info && info.height > 0 ? info.width / info.height : 595 / 842;
}

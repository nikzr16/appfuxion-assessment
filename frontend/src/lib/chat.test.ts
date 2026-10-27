import { describe, expect, it } from "vitest";

import { makeStep } from "../test/fixtures.ts";
import { canAsk, describeStep, documentIdFromPath, readStoredConversation, storeConversation } from "./chat.ts";

describe("chat helpers", () => {
  it("finds the document of a detail page only", () => {
    expect(documentIdFromPath("/documents/3721D29D-87A3-4F38-9C4C-7F50E16FB346")).toBe(
      "3721d29d-87a3-4f38-9c4c-7f50e16fb346",
    );
    expect(documentIdFromPath("/documents")).toBeUndefined();
    expect(documentIdFromPath("/documents/not-an-id")).toBeUndefined();
    expect(documentIdFromPath("/metrics")).toBeUndefined();
  });

  it("accepts questions of 3 to 500 characters", () => {
    expect(canAsk("  hi ")).toBe(false);
    expect(canAsk("Why?")).toBe(true);
    expect(canAsk("x".repeat(501))).toBe(false);
  });

  it("stores and forgets the conversation", () => {
    storeConversation("abc");
    expect(readStoredConversation()).toBe("abc");
    storeConversation(null);
    expect(readStoredConversation()).toBeNull();
  });

  it("describes tool steps in plain words", () => {
    const search = makeStep({
      tool: "search_invoices",
      arguments: { vendor: "ABC", date_from: "2026-01-01", date_to: null, min_total: 100 },
      result: { total_matches: 3 },
    });
    expect(describeStep(search)).toEqual({
      title: "Searched the invoices",
      detail: "vendor “ABC”, from 01-01-2026, total ≥ 100 · 3 matches",
      failed: false,
    });
    const history = makeStep({
      tool: "get_vendor_history",
      arguments: { document_id: "3721d29d-87a3-4f38-9c4c-7f50e16fb346" },
      result: { invoices: [{}] },
    });
    expect(describeStep(history).detail).toBe("document “3721d29d” · 1 invoice");
    const retried = makeStep({
      tool: "submit_answer",
      status: "error",
      result: null,
      error: { code: "numbers_not_found", message: "..." },
    });
    expect(describeStep(retried)).toEqual({
      title: "Wrote the answer",
      detail: "Was asked to copy numbers exactly from the data",
      failed: true,
    });
  });
});

import { describe, expect, it } from "vitest";

import { makeIssue } from "../test/fixtures.ts";
import {
  countBySeverity,
  indexIssues,
  lineRowId,
  parseIssuePath,
  sortIssues,
  targetId,
  worstSeverity,
} from "./issues.ts";

describe("parseIssuePath", () => {
  it("maps 0004 field paths to page targets", () => {
    expect(parseIssuePath("total_amount")).toEqual({ kind: "field", field: "total_amount" });
    expect(parseIssuePath("line_items")).toEqual({ kind: "table" });
    expect(parseIssuePath("line_items[2].amount")).toEqual({ kind: "line", index: 2, column: "amount" });
    expect(parseIssuePath("line_items[0]")).toEqual({ kind: "line", index: 0, column: null });
  });
});

describe("indexIssues", () => {
  const issues = [
    makeIssue({ field: "total_amount", severity: "warning" }),
    makeIssue({ field: "total_amount", severity: "error" }),
    makeIssue({ field: "line_items[1].amount", severity: "warning" }),
    makeIssue({ field: "line_items", severity: "info" }),
  ];
  const index = indexIssues(issues);

  it("groups issues by field, line, cell and table", () => {
    expect(index.forField("total_amount")).toHaveLength(2);
    expect(index.forField("vendor")).toEqual([]);
    expect(index.forLine(1)).toHaveLength(1);
    expect(index.forCell(1, "amount")).toHaveLength(1);
    expect(index.forCell(1, "quantity")).toEqual([]);
    expect(index.table).toHaveLength(1);
  });

  it("finds the worst severity and counts", () => {
    expect(worstSeverity(index.forField("total_amount"))).toBe("error");
    expect(worstSeverity([])).toBeNull();
    expect(countBySeverity(issues)).toEqual({ error: 1, warning: 2, info: 1 });
  });

  it("sorts errors first", () => {
    expect(sortIssues(issues).map((issue) => issue.severity)).toEqual(["error", "warning", "warning", "info"]);
  });
});

describe("target ids", () => {
  it("are stable DOM ids", () => {
    expect(targetId("line_items[2].amount")).toBe("issue-target-line_items-2-amount");
    expect(targetId("total_amount")).toBe("issue-target-total_amount");
    expect(lineRowId(2)).toBe("issue-target-line_items-2");
  });
});

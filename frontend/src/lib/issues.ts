/**
 * Maps validation issues onto the page (PRD D8). Issue fields are JSON paths into
 * InvoiceData from 0004: `total_amount`, `line_items` or `line_items[2].amount` (0-based).
 */
import type { Severity, ValidationIssue } from "../api/types.ts";

export type IssueTarget =
  | { kind: "field"; field: string }
  | { kind: "line"; index: number; column: string | null }
  | { kind: "table" };

const LINE_PATH = /^line_items\[(\d+)\](?:\.(\w+))?$/;

export function parseIssuePath(path: string): IssueTarget {
  if (path === "line_items") return { kind: "table" };
  const match = LINE_PATH.exec(path);
  if (match) return { kind: "line", index: Number(match[1]), column: match[2] ?? null };
  return { kind: "field", field: path };
}

/** DOM id of the element an issue points at. */
export function targetId(path: string): string {
  return `issue-target-${path.replace(/[^A-Za-z0-9_]+/g, "-").replace(/-+$/, "")}`;
}

export function lineRowId(index: number): string {
  return targetId(`line_items[${index}]`);
}

export const SEVERITY_RANK: Record<Severity, number> = { error: 0, warning: 1, info: 2 };

export function sortIssues(issues: readonly ValidationIssue[]): ValidationIssue[] {
  return [...issues].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);
}

export function worstSeverity(issues: readonly ValidationIssue[]): Severity | null {
  let worst: Severity | null = null;
  for (const issue of issues) {
    if (worst === null || SEVERITY_RANK[issue.severity] < SEVERITY_RANK[worst]) {
      worst = issue.severity;
    }
  }
  return worst;
}

export function countBySeverity(issues: readonly ValidationIssue[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
  for (const issue of issues) counts[issue.severity] += 1;
  return counts;
}

export interface IssueIndex {
  forField(field: string): ValidationIssue[];
  forLine(index: number): ValidationIssue[];
  forCell(index: number, column: string): ValidationIssue[];
  table: ValidationIssue[];
}

function push<K>(map: Map<K, ValidationIssue[]>, key: K, issue: ValidationIssue): void {
  map.set(key, [...(map.get(key) ?? []), issue]);
}

export function indexIssues(issues: readonly ValidationIssue[]): IssueIndex {
  const fields = new Map<string, ValidationIssue[]>();
  const lines = new Map<number, ValidationIssue[]>();
  const cells = new Map<string, ValidationIssue[]>();
  const table: ValidationIssue[] = [];
  for (const issue of issues) {
    const target = parseIssuePath(issue.field);
    if (target.kind === "table") table.push(issue);
    else if (target.kind === "field") push(fields, target.field, issue);
    else {
      push(lines, target.index, issue);
      if (target.column) push(cells, `${target.index}.${target.column}`, issue);
    }
  }
  return {
    forField: (field) => fields.get(field) ?? [],
    forLine: (index) => lines.get(index) ?? [],
    forCell: (index, column) => cells.get(`${index}.${column}`) ?? [],
    table,
  };
}

export const EMPTY_ISSUE_INDEX: IssueIndex = indexIssues([]);

/** Scrolls to the element an issue points at and flashes it (falls back to the line row). */
export function revealIssueTarget(path: string): void {
  const target = parseIssuePath(path);
  const element =
    document.getElementById(targetId(path)) ??
    (target.kind === "line" ? document.getElementById(lineRowId(target.index)) : null);
  if (!element) return;
  element.scrollIntoView({ behavior: "smooth", block: "center" });
  element.classList.remove("flash-highlight");
  // Restart the animation when the same issue is clicked twice.
  void element.offsetWidth;
  element.classList.add("flash-highlight");
  window.setTimeout(() => element.classList.remove("flash-highlight"), 1700);
}

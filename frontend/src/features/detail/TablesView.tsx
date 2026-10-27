import { CheckCircle2, Info, Table2 } from "lucide-react";

import type { ExtractionMethod, LayoutTable } from "../../api/types.ts";
import { Badge } from "../../components/ui/Badge.tsx";
import { cx } from "../../lib/cx.ts";
import { STRATEGY_LABEL, columnTitles, isNumericColumn, pagesLabel } from "../../lib/layout.ts";

/** Which tables fed the line items: text PDFs copy them; scans only show them to the model. */
function KindBadge({ table, source }: { table: LayoutTable; source: ExtractionMethod }) {
  if (table.kind !== "line_items") return <Badge>Other table</Badge>;
  if (source === "pdf_parser") {
    return (
      <Badge tone="success" icon={<CheckCircle2 className="size-3.5" aria-hidden />}>
        Line-item table
      </Badge>
    );
  }
  return (
    <Badge tone="info" icon={<Info className="size-3.5" aria-hidden />}>
      Hint for the model
    </Badge>
  );
}

function TableCard({ table, source }: { table: LayoutTable; source: ExtractionMethod }) {
  const titles = columnTitles(table);
  const captionId = `layout-table-${table.index}`;
  return (
    <div className="rounded-xl border border-border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h3 id={captionId} className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Table2 className="size-4 text-fg-subtle" aria-hidden />
            Table {table.index + 1}
          </h3>
          <p className="mt-0.5 text-xs text-fg-muted tabular-nums">
            {pagesLabel(table.pages)} · {table.rows.length} row{table.rows.length === 1 ? "" : "s"} ·{" "}
            {STRATEGY_LABEL[table.strategy]}
          </p>
        </div>
        <KindBadge table={table} source={source} />
      </div>
      <div className="max-h-96 overflow-auto">
        <table className="w-full min-w-[28rem] text-sm" aria-labelledby={captionId}>
          <thead className="sticky top-0 bg-surface-2">
            <tr className="text-left text-xs font-medium tracking-wide text-fg-subtle uppercase">
              {titles.map((title, index) => (
                <th
                  key={index}
                  scope="col"
                  className={cx(
                    "px-3 py-2 font-medium",
                    isNumericColumn(table.columns[index] ?? "other") && "text-right",
                  )}
                >
                  {title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {titles.map((_, index) => {
                  const value = row.cells[index] ?? null;
                  const numeric = isNumericColumn(table.columns[index] ?? "other");
                  return (
                    <td
                      key={index}
                      className={cx(
                        "px-3 py-2 align-top",
                        numeric && "text-right whitespace-nowrap tabular-nums",
                        value === null ? "text-fg-subtle" : "text-fg",
                      )}
                    >
                      {value ?? <span aria-label="empty cell">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Every table the analysis found, as real tables (PRD 0009 D11a). */
export function TablesView({ tables, source }: { tables: LayoutTable[]; source: ExtractionMethod }) {
  if (tables.length === 0) {
    return (
      <p className="text-sm text-fg-muted">
        No tables were found. Line items, if any, were read by the model from the text.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {tables.map((table) => (
        <TableCard key={table.index} table={table} source={source} />
      ))}
    </div>
  );
}

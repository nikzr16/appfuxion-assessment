import { ListChecks } from "lucide-react";
import type { ReactNode } from "react";

import type { InvoiceData, LineItem } from "../../api/types.ts";
import { SEVERITY_STYLE } from "../../components/severity.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { cx } from "../../lib/cx.ts";
import { EMPTY, formatAmount, formatQuantity } from "../../lib/format.ts";
import { lineRowId, targetId, worstSeverity, type IssueIndex } from "../../lib/issues.ts";
import { IssueMarker } from "./IssueMarker.tsx";

type Column = keyof LineItem;

function Cell({
  index,
  column,
  issues,
  numeric = false,
  children,
}: {
  index: number;
  column: Column;
  issues: IssueIndex;
  numeric?: boolean;
  children: ReactNode;
}) {
  const cellIssues = issues.forCell(index, column);
  const worst = worstSeverity(cellIssues);
  return (
    <td
      id={worst ? targetId(`line_items[${index}].${column}`) : undefined}
      className={cx(
        "px-3 py-3 align-top",
        numeric && "text-right tabular-nums whitespace-nowrap",
        worst && `rounded-lg ${SEVERITY_STYLE[worst].ring} ring-inset`,
      )}
    >
      <span className={cx("inline-flex items-start gap-1.5", numeric && "justify-end")}>
        {children}
        <IssueMarker issues={cellIssues} />
      </span>
    </td>
  );
}

/** Line items with issue rows tinted and issue cells outlined (PRD D8); totals in the footer. */
export function LineItemsTable({ data, issues }: { data: InvoiceData; issues: IssueIndex }) {
  const amount = (value: string | null) => formatAmount(value, data.currency);
  const tableIssues = issues.table;
  const worstTable = worstSeverity(tableIssues);

  return (
    <Card aria-labelledby="line-items-title">
      <CardHeader
        id="line-items-title"
        icon={<ListChecks className="size-4.5" aria-hidden />}
        title="Line items"
        description={
          data.line_items.length
            ? `${data.line_items.length} line${data.line_items.length === 1 ? "" : "s"}${
                data.currency ? ` · amounts in ${data.currency}` : ""
              }`
            : "No line items were found on the document."
        }
      />
      {worstTable && (
        <div
          id={targetId("line_items")}
          className={cx(
            "mx-5 mt-4 flex gap-2 rounded-xl px-3 py-2.5 text-sm sm:mx-6",
            SEVERITY_STYLE[worstTable].tint,
          )}
        >
          <IssueMarker issues={tableIssues} />
          <span className="text-fg">{tableIssues.map((issue) => issue.message).join(" ")}</span>
        </div>
      )}
      {data.line_items.length > 0 && (
        <CardBody className="px-2 sm:px-3">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-medium tracking-wide text-fg-subtle uppercase">
                  <th scope="col" className="w-10 px-3 py-2 font-medium">#</th>
                  <th scope="col" className="px-3 py-2 font-medium">Description</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Qty</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Unit price</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.line_items.map((line, index) => {
                  const worst = worstSeverity(issues.forLine(index));
                  return (
                    <tr key={index} id={lineRowId(index)} className={cx(worst && SEVERITY_STYLE[worst].tint)}>
                      <td className="px-3 py-3 align-top text-fg-subtle tabular-nums">{index + 1}</td>
                      <Cell index={index} column="description" issues={issues}>
                        <span className={line.description ? "text-fg" : "text-fg-subtle"}>
                          {line.description ?? EMPTY}
                        </span>
                      </Cell>
                      <Cell index={index} column="quantity" issues={issues} numeric>
                        {formatQuantity(line.quantity)}
                      </Cell>
                      <Cell index={index} column="unit_price" issues={issues} numeric>
                        {amount(line.unit_price)}
                      </Cell>
                      <Cell index={index} column="amount" issues={issues} numeric>
                        <span className="font-medium text-fg">{amount(line.amount)}</span>
                      </Cell>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="border-t-2 border-border text-sm">
                {[
                  { label: "Subtotal", value: data.subtotal },
                  { label: "Tax", value: data.tax },
                ].map(({ label, value }) => (
                  <tr key={label}>
                    <td colSpan={4} className="px-3 pt-3 text-right text-fg-muted">{label}</td>
                    <td className="px-3 pt-3 text-right text-fg tabular-nums">{amount(value)}</td>
                  </tr>
                ))}
                <tr>
                  <td colSpan={4} className="px-3 pt-2 pb-1 text-right font-semibold text-fg">Total</td>
                  <td className="px-3 pt-2 pb-1 text-right font-semibold whitespace-nowrap text-fg tabular-nums">
                    {data.currency && <span className="mr-1 text-xs font-medium text-fg-subtle">{data.currency}</span>}
                    {amount(data.total_amount)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </CardBody>
      )}
      {data.line_items.length === 0 && <div className="pb-5" />}
    </Card>
  );
}

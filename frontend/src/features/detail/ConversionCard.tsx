import { ArrowRight, Repeat } from "lucide-react";

import type { ConversionResult } from "../../api/types.ts";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { formatDate, formatDecimal, formatMoney } from "../../lib/format.ts";

/** Total converted to the base currency with a static, dated rate (0004). */
export function ConversionCard({ conversion }: { conversion: ConversionResult }) {
  return (
    <Card aria-labelledby="conversion-title">
      <CardHeader
        id="conversion-title"
        icon={<Repeat className="size-4.5" aria-hidden />}
        title="Currency conversion"
        description={`Total converted to ${conversion.to_currency}.`}
      />
      <CardBody>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 tabular-nums">
          <span className="text-sm text-fg-muted">
            {formatMoney(conversion.original_amount, conversion.from_currency)}
          </span>
          <ArrowRight className="size-4 text-fg-subtle" aria-hidden />
          <span className="text-lg font-semibold text-fg">
            {formatMoney(conversion.converted_amount, conversion.to_currency)}
          </span>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-fg-subtle">Rate</dt>
            <dd className="text-fg tabular-nums">
              1 {conversion.from_currency} = {formatDecimal(conversion.rate)} {conversion.to_currency}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-fg-subtle">Rate date</dt>
            <dd className="text-fg tabular-nums">{formatDate(conversion.rate_date)}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-xs text-fg-subtle">Source</dt>
            <dd className="break-words text-fg-muted">{conversion.source}</dd>
          </div>
        </dl>
      </CardBody>
    </Card>
  );
}

import { Images, LayoutTemplate, ScanEye, Table2 } from "lucide-react";

import type { VisionMetrics } from "../../api/types.ts";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { formatPercent } from "../../lib/format.ts";
import { Stat } from "./GuardrailsSection.tsx";

/** Tables, layout and vision use in the window (feature 0009, PRD D12). */
export function VisionSection({ data }: { data: VisionMetrics }) {
  const items = data.line_items_from_table + data.line_items_from_model;
  const empty = data.layouts_analysed === 0 && items === 0 && data.pages_via_vision === 0;
  return (
    <Card aria-labelledby="metrics-vision">
      <CardHeader
        id="metrics-vision"
        icon={<ScanEye className="size-4.5" aria-hidden />}
        title="Vision"
        description="Tables and layout found, where line items came from, and what went through the vision model."
      />
      <CardBody>
        {empty ? (
          <p className="text-sm text-fg-muted">
            No document in this window has been analysed for tables yet. New and reprocessed documents are.
          </p>
        ) : (
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              icon={<LayoutTemplate className="size-4" aria-hidden />}
              label="With a line-item table"
              value={`${data.documents_with_line_item_table} of ${data.layouts_analysed}`}
              hint={`${data.tables_found} table${data.tables_found === 1 ? "" : "s"} found`}
            />
            <Stat
              icon={<Table2 className="size-4" aria-hidden />}
              label="Line items from tables"
              value={formatPercent(data.line_items_table_share)}
              hint={`${data.line_items_from_table} of ${items} copied by code`}
            />
            <Stat
              icon={<ScanEye className="size-4" aria-hidden />}
              label="Pages read by vision"
              value={data.pages_via_vision}
              hint="Scans and photos, one call per page"
            />
            <Stat
              icon={<Images className="size-4" aria-hidden />}
              label="Multimodal extractions"
              value={data.multimodal_calls}
              hint="Field extraction with the page images"
            />
          </dl>
        )}
      </CardBody>
    </Card>
  );
}

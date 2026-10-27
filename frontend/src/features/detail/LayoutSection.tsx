import { LayoutTemplate } from "lucide-react";
import { useEffect, useState } from "react";

import { useLayout } from "../../api/queries.ts";
import type { LayoutResponse } from "../../api/types.ts";
import { ErrorAlert } from "../../components/ui/Alert.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { Tabs } from "../../components/ui/Tabs.tsx";
import { formatRelative, formatTimestamp } from "../../lib/format.ts";
import type { PageHighlight } from "../../lib/layout.ts";
import { PagePreview } from "./PagePreview.tsx";
import { TablesView } from "./TablesView.tsx";

type View = "tables" | "page";

const VIEWS = [
  { value: "tables", label: "Tables" },
  { value: "page", label: "Page" },
] as const;

const SOURCE_LABEL = {
  pdf_parser: "Found in the PDF by code (no AI)",
  vision: "Read from the page images by the vision model",
} as const;

function describe(layout: LayoutResponse): string {
  const tables = layout.tables.length;
  const blocks = layout.blocks.length;
  return `${tables} table${tables === 1 ? "" : "s"} · ${blocks} block${blocks === 1 ? "" : "s"} · ${
    layout.page_count
  } page${layout.page_count === 1 ? "" : "s"}`;
}

/**
 * Tables & layout (feature 0009, PRD D11): the tables the analysis found and the page with
 * its blocks. A `highlight` ("Show on page" from the line items) switches to the page view.
 */
export function LayoutSection({
  documentId,
  highlight = null,
}: {
  documentId: string;
  highlight?: PageHighlight | null;
}) {
  const query = useLayout(documentId, { enabled: true });
  const [view, setView] = useState<View>("tables");
  const [page, setPage] = useState(1);

  // A new "Show on page" click opens its page (state adjusted while rendering, not in an effect).
  const [shown, setShown] = useState<number | null>(null);
  if (highlight && highlight.nonce !== shown) {
    setShown(highlight.nonce);
    setView("page");
    setPage(highlight.page);
  }
  useEffect(() => {
    if (highlight) document.getElementById("layout")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [highlight]);

  const layout = query.data;
  const panelId = "layout-panel";

  return (
    <Card aria-labelledby="layout-title" id="layout" className="scroll-mt-24">
      <CardHeader
        id="layout-title"
        icon={<LayoutTemplate className="size-4.5" aria-hidden />}
        title="Tables & layout"
        description={layout ? describe(layout) : "The document's tables and where each part sits on the page."}
        actions={
          layout && (
            <Tabs label="Layout view" options={VIEWS} value={view} onChange={setView} controls={panelId} />
          )
        }
      />
      <CardBody>
        {query.isPending ? (
          <div className="space-y-3" aria-label="Loading tables and layout">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-40 rounded-xl" />
          </div>
        ) : query.isError ? (
          <ErrorAlert error={query.error} onRetry={() => void query.refetch()} />
        ) : !layout ? (
          <p className="text-sm text-fg-muted">
            Layout not analysed — reprocess the document to find its tables and layout.
          </p>
        ) : (
          <div id={panelId} role="tabpanel" aria-label={view === "tables" ? "Tables" : "Page"}>
            <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <Badge tone="accent">{SOURCE_LABEL[layout.source]}</Badge>
              <span>
                Analysed{" "}
                <time dateTime={layout.created_at} title={formatTimestamp(layout.created_at)}>
                  {formatRelative(layout.created_at)}
                </time>
                {layout.history.length > 0 &&
                  ` · ${layout.history.length} earlier analys${layout.history.length === 1 ? "is" : "es"} kept`}
              </span>
            </div>
            {view === "tables" ? (
              <TablesView tables={layout.tables} source={layout.source} />
            ) : (
              <PagePreview
                documentId={documentId}
                layout={layout}
                page={Math.min(Math.max(page, 1), layout.page_count)}
                onPageChange={setPage}
                highlight={highlight}
              />
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

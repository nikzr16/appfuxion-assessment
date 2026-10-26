import { FileStack, Inbox, LoaderCircle, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import { PAGE_SIZE, POLL_INTERVAL_MS, useDocuments } from "../../api/queries.ts";
import type { DocumentStatus } from "../../api/types.ts";
import { PageHeader } from "../../components/PageHeader.tsx";
import { Alert, ErrorAlert } from "../../components/ui/Alert.tsx";
import { Button } from "../../components/ui/Button.tsx";
import { buttonClasses } from "../../components/ui/buttonClasses.ts";
import { Card } from "../../components/ui/Card.tsx";
import { EmptyState } from "../../components/ui/EmptyState.tsx";
import { Pagination } from "../../components/ui/Pagination.tsx";
import { Tabs, type TabOption } from "../../components/ui/Tabs.tsx";
import { useDocumentTitle } from "../../lib/useDocumentTitle.ts";
import type { UploadedState } from "../upload/useUploadQueue.ts";
import { DocumentsTable, DocumentsTableSkeleton } from "./DocumentsTable.tsx";

type Filter = "all" | DocumentStatus;

const FILTERS: readonly TabOption<Filter>[] = [
  { value: "all", label: "All" },
  { value: "processing", label: "Processing" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

const EMPTY_TEXT: Record<Exclude<Filter, "all">, string> = {
  processing: "Nothing is processing right now.",
  completed: "No documents have finished processing yet.",
  failed: "No documents have failed. Nice.",
};

/** Filter and page live in the URL so reloads and the back button keep them (PRD D6). */
function useListParams() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("status");
  const filter: Filter = FILTERS.some((option) => option.value === raw) ? (raw as Filter) : "all";
  const parsedPage = Number.parseInt(params.get("page") ?? "1", 10);
  const page = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1;

  function update(next: { filter?: Filter; page?: number }) {
    const nextFilter = next.filter ?? filter;
    const nextPage = next.page ?? (next.filter ? 1 : page);
    const search = new URLSearchParams();
    if (nextFilter !== "all") search.set("status", nextFilter);
    if (nextPage > 1) search.set("page", String(nextPage));
    setParams(search);
  }

  return { filter, page, update };
}

export default function DocumentsPage() {
  useDocumentTitle("Documents");
  const { filter, page, update } = useListParams();
  const location = useLocation();
  const uploadedIds = (location.state as UploadedState | null)?.uploaded;
  const highlight = useMemo(() => new Set(uploadedIds ?? []), [uploadedIds]);
  const [showUploaded, setShowUploaded] = useState(Boolean(uploadedIds?.length));

  const status = filter === "all" ? undefined : filter;
  const query = useDocuments(status, page);
  const items = query.data?.items ?? [];
  const polling = items.some((item) => item.status === "processing");

  return (
    <>
      <PageHeader
        title="Documents"
        description="Every upload, newest first. Open one to see its data, validation and summary."
        actions={
          <Link to="/" className={buttonClasses("primary")}>
            <Upload className="size-4" aria-hidden />
            Upload
          </Link>
        }
      />

      {showUploaded && uploadedIds && (
        <Alert
          tone="success"
          title={`${uploadedIds.length} document${uploadedIds.length === 1 ? "" : "s"} uploaded`}
          className="mb-6"
          action={
            <Button variant="ghost" size="sm" onClick={() => setShowUploaded(false)}>
              Dismiss
            </Button>
          }
        >
          Processing has started. This list updates every {POLL_INTERVAL_MS / 1000} seconds until they finish.
        </Alert>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          label="Filter by status"
          options={FILTERS}
          value={filter}
          onChange={(value) => update({ filter: value })}
          controls="documents-panel"
        />
        {polling && (
          <p className="inline-flex items-center gap-2 text-xs text-fg-subtle">
            <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
            Updating every {POLL_INTERVAL_MS / 1000} s while documents process
          </p>
        )}
      </div>

      <Card id="documents-panel" role="tabpanel" aria-busy={query.isFetching} className="overflow-hidden">
        {query.isPending ? (
          <DocumentsTableSkeleton />
        ) : query.isError && !query.data ? (
          <div className="p-5 sm:p-6">
            <ErrorAlert error={query.error} onRetry={() => void query.refetch()} />
          </div>
        ) : items.length === 0 ? (
          filter === "all" && page === 1 ? (
            <EmptyState
              icon={<FileStack className="size-6" aria-hidden />}
              title="No documents yet"
              description="Upload your first invoice or receipt to see its extracted data here."
              action={
                <Link to="/" className={buttonClasses("primary")}>
                  <Upload className="size-4" aria-hidden />
                  Upload a document
                </Link>
              }
            />
          ) : (
            <EmptyState
              icon={<Inbox className="size-6" aria-hidden />}
              title={page > 1 ? "Nothing on this page" : "No matching documents"}
              description={page > 1 ? "Go back to the first page." : EMPTY_TEXT[filter as Exclude<Filter, "all">]}
              action={
                page > 1 ? (
                  <Button variant="secondary" onClick={() => update({ page: 1 })}>
                    First page
                  </Button>
                ) : undefined
              }
            />
          )
        ) : (
          <DocumentsTable documents={items} highlight={highlight} />
        )}
      </Card>

      {query.data && query.data.total > PAGE_SIZE && (
        <div className="mt-4">
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={query.data.total}
            onPageChange={(next) => update({ page: next })}
          />
        </div>
      )}
    </>
  );
}

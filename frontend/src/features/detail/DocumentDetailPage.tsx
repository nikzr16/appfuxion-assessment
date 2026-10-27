import { ArrowLeft, FileX, LoaderCircle, WifiOff } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import {
  POLL_INTERVAL_MS,
  useDocument,
  useExtraction,
  useLayout,
  useRefreshOnFinish,
  useResult,
  useRuns,
  useTrace,
} from "../../api/queries.ts";
import type { AgentResult, DocumentRead } from "../../api/types.ts";
import { FileIcon } from "../../components/FileIcon.tsx";
import { StatusBadge } from "../../components/StatusBadge.tsx";
import { Alert, ErrorAlert } from "../../components/ui/Alert.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { buttonClasses } from "../../components/ui/buttonClasses.ts";
import { Card } from "../../components/ui/Card.tsx";
import { CopyButton } from "../../components/ui/CopyButton.tsx";
import { EmptyState } from "../../components/ui/EmptyState.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { useAnnounce } from "../../components/ui/announce.ts";
import { isNetworkError, isNotFound } from "../../lib/errors.ts";
import type { TextHighlight } from "../../lib/confidence.ts";
import { fileKind, formatBytes, formatRelative, formatTimestamp } from "../../lib/format.ts";
import { EMPTY_ISSUE_INDEX, indexIssues } from "../../lib/issues.ts";
import { lineItemLocation, type PageHighlight } from "../../lib/layout.ts";
import { useDocumentTitle } from "../../lib/useDocumentTitle.ts";
import { AgentActivity } from "./AgentActivity.tsx";
import { NeedsReviewBanner } from "./ConfidenceSummary.tsx";
import { ConversionCard } from "./ConversionCard.tsx";
import { IssuesList } from "./IssuesList.tsx";
import { LayoutSection } from "./LayoutSection.tsx";
import { LineItemsTable, type ShowOnPageHandler } from "./LineItemsTable.tsx";
import { RawTextSection } from "./RawTextSection.tsx";
import { ReprocessButton } from "./ReprocessButton.tsx";
import { StructuredData, type LocateHandler } from "./StructuredData.tsx";
import { SummaryCard } from "./SummaryCard.tsx";
import { TraceSection } from "./TraceSection.tsx";
import { VendorHistorySection } from "./VendorHistorySection.tsx";
import { splitError } from "./labels.ts";

function BackLink() {
  return (
    <Link
      to="/documents"
      className="inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-fg-muted hover:text-fg"
    >
      <ArrowLeft className="size-4" aria-hidden />
      Documents
    </Link>
  );
}

function DetailHeader({
  document,
  reconnecting,
  onAlreadyProcessing,
}: {
  document: DocumentRead;
  reconnecting: boolean;
  onAlreadyProcessing: () => void;
}) {
  return (
    <div className="mb-8">
      <BackLink />
      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <FileIcon contentType={document.content_type} className="size-12 rounded-2xl" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1
                tabIndex={-1}
                className="min-w-0 text-xl font-semibold tracking-tight break-all text-fg outline-none sm:text-2xl"
              >
                {document.filename}
              </h1>
              {document.version > 1 && <Badge>v{document.version}</Badge>}
              <StatusBadge status={document.status} />
            </div>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-fg-muted">
              <span>{fileKind(document.content_type)}</span>
              <span aria-hidden>·</span>
              <span className="tabular-nums">{formatBytes(document.size_bytes)}</span>
              <span aria-hidden>·</span>
              <span>
                Uploaded{" "}
                <time dateTime={document.created_at} title={formatRelative(document.created_at)} className="tabular-nums">
                  {formatTimestamp(document.created_at)}
                </time>
              </span>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center">
                <span className="font-mono text-xs text-fg-subtle" title={document.document_id}>
                  {document.document_id.slice(0, 8)}
                </span>
                <CopyButton value={document.document_id} label="Copy document ID" />
              </span>
            </p>
            {reconnecting && (
              <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-warning">
                <WifiOff className="size-3.5" aria-hidden />
                Connection lost, reconnecting…
              </p>
            )}
          </div>
        </div>
        <ReprocessButton
          documentId={document.document_id}
          disabled={document.status === "processing"}
          onAlreadyProcessing={onAlreadyProcessing}
        />
      </div>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading document">
      <Skeleton className="h-4 w-24" />
      <div className="mt-4 mb-8 flex items-center gap-4">
        <Skeleton className="size-12 rounded-2xl" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-6 w-1/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </div>
      <div className="space-y-6">
        <Skeleton className="h-48 rounded-2xl" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Skeleton className="h-72 rounded-2xl lg:col-span-2" />
          <Skeleton className="h-72 rounded-2xl" />
        </div>
      </div>
    </div>
  );
}

function ProcessingBanner() {
  return (
    <Card className="mb-6 flex items-center gap-4 p-5 sm:p-6">
      <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent">
        <LoaderCircle className="size-5 animate-spin" aria-hidden />
      </span>
      <div>
        <p className="text-base font-semibold text-fg">Processing your document</p>
        <p className="text-sm text-fg-muted">
          The agents are reading, extracting and validating it. This page checks every{" "}
          {POLL_INTERVAL_MS / 1000} seconds and shows the result as soon as it is ready.
        </p>
      </div>
    </Card>
  );
}

/** Why a result shows no badges: unknown documents have none; older runs predate 0008. */
function confidenceNote(result: AgentResult): string | undefined {
  if (result.confidence || result.structured_data.document_type === "unknown") return undefined;
  return "Confidence not available for this result — reprocess the document to compute it.";
}

function CompletedView({
  documentId,
  onLocate,
  onShowOnPage,
}: {
  documentId: string;
  onLocate: LocateHandler;
  onShowOnPage: ShowOnPageHandler;
}) {
  const result = useResult(documentId, { enabled: true });
  const extraction = useExtraction(documentId, { enabled: true });
  const layout = useLayout(documentId, { enabled: true });
  const issues = useMemo(
    () => (result.data ? indexIssues(result.data.validation.issues) : EMPTY_ISSUE_INDEX),
    [result.data],
  );

  if (result.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-72 rounded-2xl" />
      </div>
    );
  }
  if (result.isError) return <ErrorAlert error={result.error} onRetry={() => void result.refetch()} />;

  const data = result.data.structured_data;
  const confidence = result.data.confidence ?? null;
  return (
    <div className="space-y-6">
      {confidence && <NeedsReviewBanner report={confidence} onLocate={onLocate} />}
      <SummaryCard result={result.data} />
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <StructuredData
            data={data}
            issues={issues}
            confidence={confidence}
            confidenceNote={confidenceNote(result.data)}
            onLocate={onLocate}
          />
          <LineItemsTable
            data={data}
            issues={issues}
            confidence={confidence}
            onLocate={onLocate}
            source={extraction.data?.line_items_source ?? null}
            locateRow={(index) => lineItemLocation(confidence, layout.data, index)}
            onShowOnPage={onShowOnPage}
          />
        </div>
        <div className="min-w-0 space-y-6 lg:sticky lg:top-24">
          <IssuesList report={result.data.validation} currency={data.currency} />
          {result.data.conversion && <ConversionCard conversion={result.data.conversion} />}
        </div>
      </div>
      {data.document_type !== "unknown" && <VendorHistorySection documentId={documentId} />}
    </div>
  );
}

function FailedView({ document }: { document: DocumentRead }) {
  const extraction = useExtraction(document.document_id, { enabled: true });
  const { code, message } = splitError(document.error ?? "Processing failed for an unknown reason.");

  return (
    <div className="space-y-6">
      <Alert tone="danger" role="alert" title="Processing failed">
        <p className="text-fg">{message}</p>
        {code && <p className="mt-1 font-mono text-xs text-fg-subtle">{code}</p>}
        <p className="mt-2">You can reprocess the document to try again.</p>
      </Alert>
      {extraction.data && (
        <>
          <StructuredData
            data={extraction.data.structured_data}
            issues={EMPTY_ISSUE_INDEX}
            title="Partial data"
            description="Saved before the failure. It was not validated."
          />
          <LineItemsTable data={extraction.data.structured_data} issues={EMPTY_ISSUE_INDEX} />
        </>
      )}
    </div>
  );
}

const STATUS_ANNOUNCEMENT = {
  completed: "Processing complete.",
  failed: "Processing failed.",
} as const;

export default function DocumentDetailPage() {
  const { id = "" } = useParams();
  const document = useDocument(id);
  const status = document.data?.status;
  const live = status === "processing";
  const runs = useRuns(id, { live });
  const [traceRunId, setTraceRunId] = useState<string | undefined>(undefined);
  const trace = useTrace(id, traceRunId, { live: live && traceRunId === undefined });
  const latestTrace = useTrace(id, undefined, { live });
  const announce = useAnnounce();
  const [alreadyProcessing, setAlreadyProcessing] = useState(false);
  const [highlight, setHighlight] = useState<TextHighlight | null>(null);
  const locate: LocateHandler = (span) => setHighlight({ ...span, nonce: Date.now() });
  const [pageHighlight, setPageHighlight] = useState<PageHighlight | null>(null);
  const showOnPage: ShowOnPageHandler = (target) => setPageHighlight({ ...target, nonce: Date.now() });
  useRefreshOnFinish(id, status);
  useDocumentTitle(document.data?.filename ?? (document.isError ? "Document not found" : "Document"));

  const previous = useRef(status);
  useEffect(() => {
    if (previous.current === "processing" && (status === "completed" || status === "failed")) {
      announce(STATUS_ANNOUNCEMENT[status]);
    }
    previous.current = status;
  }, [status, announce]);

  if (document.isPending) return <DetailSkeleton />;

  if (document.isError && !document.data) {
    return (
      <>
        <BackLink />
        {isNotFound(document.error) ? (
          <EmptyState
            pageHeading
            className="mt-6"
            icon={<FileX className="size-6" aria-hidden />}
            title="Document not found"
            description="It may have been removed, or the link is wrong."
            action={
              <Link to="/documents" className={buttonClasses("primary")}>
                Back to documents
              </Link>
            }
          />
        ) : (
          <>
            <h1 tabIndex={-1} className="sr-only">
              Could not load the document
            </h1>
            <ErrorAlert className="mt-6" error={document.error} onRetry={() => void document.refetch()} />
          </>
        )}
      </>
    );
  }

  const doc = document.data;
  const reconnecting = document.isRefetchError && isNetworkError(document.error);

  return (
    <>
      <DetailHeader
        document={doc}
        reconnecting={reconnecting}
        onAlreadyProcessing={() => setAlreadyProcessing(true)}
      />

      {alreadyProcessing && doc.status === "processing" && (
        <Alert tone="info" title="Already processing" className="mb-6">
          This document was already being processed. The page will update when it finishes.
        </Alert>
      )}

      {doc.status === "processing" && <ProcessingBanner />}
      {doc.status === "completed" && (
        <CompletedView documentId={doc.document_id} onLocate={locate} onShowOnPage={showOnPage} />
      )}
      {doc.status === "failed" && <FailedView document={doc} />}

      <div className="mt-6 space-y-6">
        {doc.status !== "processing" && <LayoutSection documentId={doc.document_id} highlight={pageHighlight} />}
        <AgentActivity
          runs={runs.data}
          isPending={runs.isPending}
          error={runs.error}
          onRetry={() => void runs.refetch()}
          live={live}
          trace={latestTrace.data}
        />
        <TraceSection
          trace={trace.data}
          isPending={trace.isPending}
          error={trace.error}
          onRetry={() => void trace.refetch()}
          runs={runs.data}
          runId={traceRunId}
          onRunChange={setTraceRunId}
        />
        {doc.status !== "processing" && <RawTextSection documentId={doc.document_id} highlight={highlight} />}
      </div>
    </>
  );
}

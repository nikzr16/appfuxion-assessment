import { ChevronRight } from "lucide-react";
import { Link } from "react-router";

import type { DocumentRead } from "../../api/types.ts";
import { FileIcon } from "../../components/FileIcon.tsx";
import { StatusBadge } from "../../components/StatusBadge.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { cx } from "../../lib/cx.ts";
import { fileKind, formatBytes, formatRelative, formatTimestamp } from "../../lib/format.ts";

interface DocumentsTableProps {
  documents: DocumentRead[];
  highlight: ReadonlySet<string>;
}

function FileName({ document, isNew }: { document: DocumentRead; isNew: boolean }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="truncate font-medium text-fg">{document.filename}</span>
      {document.version > 1 && <Badge>v{document.version}</Badge>}
      {isNew && <Badge tone="accent">New</Badge>}
    </span>
  );
}

function ErrorLine({ error }: { error: string }) {
  return (
    <span className="mt-0.5 line-clamp-1 block text-xs text-danger" title={error}>
      {error}
    </span>
  );
}

function Uploaded({ value }: { value: string }) {
  return (
    <time dateTime={value} title={formatRelative(value)} className="tabular-nums">
      {formatTimestamp(value)}
    </time>
  );
}

/** Table on wide screens, stacked cards on phones (PRD D6, D13). Every row links to the detail page. */
export function DocumentsTable({ documents, highlight }: DocumentsTableProps) {
  return (
    <>
      <div className="relative hidden overflow-x-auto sm:block">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs font-medium tracking-wide text-fg-subtle uppercase">
              <th scope="col" className="py-3 pr-4 pl-6 font-medium">File</th>
              <th scope="col" className="px-4 py-3 font-medium">Type</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">Size</th>
              <th scope="col" className="px-4 py-3 font-medium">Status</th>
              <th scope="col" className="py-3 pr-6 pl-4 font-medium">Uploaded</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {documents.map((document) => (
              <tr
                key={document.document_id}
                className={cx(
                  "group relative transition-colors hover:bg-surface-2 has-[a:focus-visible]:bg-surface-2",
                  highlight.has(document.document_id) && "bg-accent-soft/60",
                )}
              >
                <td className="max-w-0 py-3.5 pr-4 pl-6 sm:w-1/2">
                  <div className="flex items-center gap-3">
                    <FileIcon contentType={document.content_type} className="size-9" />
                    <div className="min-w-0">
                      <Link
                        to={`/documents/${document.document_id}`}
                        className="block outline-none after:absolute after:inset-0 after:content-['']"
                      >
                        <FileName document={document} isNew={highlight.has(document.document_id)} />
                      </Link>
                      {document.status === "failed" && document.error && <ErrorLine error={document.error} />}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3.5 text-fg-muted">{fileKind(document.content_type)}</td>
                <td className="px-4 py-3.5 text-right text-fg-muted tabular-nums">
                  {formatBytes(document.size_bytes)}
                </td>
                <td className="px-4 py-3.5">
                  <StatusBadge status={document.status} />
                </td>
                <td className="py-3.5 pr-6 pl-4 text-fg-muted">
                  <span className="flex items-center justify-between gap-2">
                    <Uploaded value={document.created_at} />
                    <ChevronRight
                      className="size-4 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100"
                      aria-hidden
                    />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="divide-y divide-border sm:hidden">
        {documents.map((document) => (
          <li key={document.document_id}>
            <Link
              to={`/documents/${document.document_id}`}
              className={cx(
                "flex items-start gap-3 px-4 py-4 hover:bg-surface-2",
                highlight.has(document.document_id) && "bg-accent-soft/60",
              )}
            >
              <FileIcon contentType={document.content_type} className="size-9" />
              <div className="min-w-0 flex-1 text-sm">
                <FileName document={document} isNew={highlight.has(document.document_id)} />
                {document.status === "failed" && document.error && <ErrorLine error={document.error} />}
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
                  <StatusBadge status={document.status} />
                  <span>
                    {fileKind(document.content_type)} · {formatBytes(document.size_bytes)}
                  </span>
                  <Uploaded value={document.created_at} />
                </div>
              </div>
              <ChevronRight className="mt-2 size-4 shrink-0 text-fg-subtle" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

export function DocumentsTableSkeleton() {
  return (
    <div className="divide-y divide-border" aria-hidden>
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} className="flex items-center gap-4 px-4 py-4 sm:px-6">
          <div className="size-9 shrink-0 animate-pulse rounded-xl bg-surface-2" />
          <div className="flex-1 space-y-2">
            <div className="h-3.5 w-1/3 animate-pulse rounded bg-surface-2" />
            <div className="h-3 w-1/5 animate-pulse rounded bg-surface-2 sm:hidden" />
          </div>
          <div className="hidden h-5 w-20 animate-pulse rounded-full bg-surface-2 sm:block" />
          <div className="hidden h-3.5 w-28 animate-pulse rounded bg-surface-2 sm:block" />
        </div>
      ))}
    </div>
  );
}

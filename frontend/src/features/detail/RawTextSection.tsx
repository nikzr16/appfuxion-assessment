import { ChevronDown, ScanText } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useText } from "../../api/queries.ts";
import { ErrorAlert } from "../../components/ui/Alert.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Card } from "../../components/ui/Card.tsx";
import { CopyButton } from "../../components/ui/CopyButton.tsx";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { splitAt, type TextHighlight } from "../../lib/confidence.ts";

const METHOD_LABEL = { pdf_parser: "PDF text layer", vision: "Vision model (OCR)" } as const;

/**
 * Collapsed by default; the text is fetched only the first time it is opened (PRD D7).
 * A `highlight` (feature 0008 "Show in text") opens it, marks the span and scrolls to it.
 */
export function RawTextSection({ documentId, highlight = null }: { documentId: string; highlight?: TextHighlight | null }) {
  const [opened, setOpened] = useState(false);
  const query = useText(documentId, { enabled: opened });
  const details = useRef<HTMLDetailsElement>(null);
  const mark = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!highlight || !details.current) return;
    details.current.open = true;
    setOpened(true);
  }, [highlight]);

  const text = query.data?.raw_text;
  useEffect(() => {
    if (!highlight || text === undefined || !mark.current) return;
    mark.current.scrollIntoView({ behavior: "smooth", block: "center" });
    mark.current.focus({ preventScroll: true });
  }, [highlight, text]);

  const parts = text === undefined ? null : splitAt(text, highlight);

  return (
    <Card className="overflow-hidden" id="raw-text">
      <details ref={details} onToggle={(event) => event.currentTarget.open && setOpened(true)} className="group">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 hover:bg-surface-2 sm:px-6 [&::-webkit-details-marker]:hidden">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
            <ScanText className="size-4.5" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-base font-semibold text-fg">Raw text</span>
            <span className="block text-sm text-fg-muted">The text the AI read from the file.</span>
          </span>
          <ChevronDown className="size-5 text-fg-subtle transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div className="border-t border-border px-5 py-4 sm:px-6">
          {query.isPending ? (
            <div className="space-y-2" aria-label="Loading raw text">
              <Skeleton className="h-3.5 w-3/4" />
              <Skeleton className="h-3.5 w-2/3" />
              <Skeleton className="h-3.5 w-5/6" />
            </div>
          ) : query.isError ? (
            <ErrorAlert error={query.error} onRetry={() => void query.refetch()} />
          ) : query.data === null || query.data === undefined ? (
            <p className="text-sm text-fg-muted">No text was saved for this document.</p>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                  <Badge tone="accent">{METHOD_LABEL[query.data.method]}</Badge>
                  <Badge>
                    {query.data.page_count} page{query.data.page_count === 1 ? "" : "s"}
                  </Badge>
                </div>
                <CopyButton value={query.data.raw_text} label="Copy raw text" showLabel />
              </div>
              <pre className="max-h-96 overflow-auto rounded-xl bg-surface-2 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap text-fg">
                {parts ? (
                  <>
                    {parts.before}
                    <mark
                      ref={mark}
                      tabIndex={-1}
                      className="rounded bg-highlight px-0.5 text-fg ring-2 ring-accent/60 outline-none"
                    >
                      {parts.match}
                    </mark>
                    {parts.after}
                  </>
                ) : (
                  query.data.raw_text
                )}
              </pre>
            </>
          )}
        </div>
      </details>
    </Card>
  );
}

import { ChevronLeft, ChevronRight, ImageOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { pageImageUrl } from "../../api/client.ts";
import type { LayoutBlock, LayoutResponse } from "../../api/types.ts";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { cx } from "../../lib/cx.ts";
import { BLOCK_META, BLOCK_PAD, blockCounts, boxStyle, pageAspect, type PageHighlight } from "../../lib/layout.ts";

function PageSwitcher({
  page,
  count,
  onChange,
}: {
  page: number;
  count: number;
  onChange: (page: number) => void;
}) {
  if (count <= 1) return null;
  const button =
    "inline-grid size-8 place-items-center rounded-lg border border-border text-fg-muted hover:bg-surface-2 hover:text-fg disabled:pointer-events-none disabled:opacity-40";
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className={button}
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        aria-label="Previous page"
      >
        <ChevronLeft className="size-4" aria-hidden />
      </button>
      <span className="min-w-20 text-center text-sm text-fg-muted tabular-nums" aria-live="polite">
        Page {page} of {count}
      </span>
      <button
        type="button"
        className={button}
        onClick={() => onChange(page + 1)}
        disabled={page >= count}
        aria-label="Next page"
      >
        <ChevronRight className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/** A block's outline on the page: its colour, a number (all sizes) and its label (sm+). */
function BlockBox({ block, active }: { block: LayoutBlock; active: boolean }) {
  if (!block.box) return null;
  const meta = BLOCK_META[block.type];
  const nearTop = block.box[1] < 0.035;
  return (
    <div
      className={cx(
        "pointer-events-none absolute rounded-sm border-2 transition-shadow",
        meta.border,
        active && "shadow-[0_0_0_3px_var(--ring)]",
      )}
      style={boxStyle(block.box, BLOCK_PAD)}
    >
      <span
        className={cx(
          // Dark ink on white: the chip sits on the page image, which is white in both themes.
          "absolute left-[-2px] inline-flex items-center gap-1 rounded-sm border-2 bg-white px-1 text-[10px] leading-tight font-semibold whitespace-nowrap text-slate-900",
          meta.border,
          nearTop ? "top-[-2px]" : "top-0 -translate-y-full",
        )}
      >
        <span className="tabular-nums">{block.order + 1}</span>
        <span className="hidden sm:inline">{meta.label}</span>
      </span>
    </div>
  );
}

function Legend({ layout, page }: { layout: LayoutResponse; page: number }) {
  const counts = blockCounts(layout, page);
  if (counts.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-fg-muted" aria-label="Block types on this page">
      {counts.map(({ type, count }) => {
        const { label, Icon, swatch } = BLOCK_META[type];
        return (
          <li key={type} className="inline-flex items-center gap-1.5">
            <span className={cx("size-2.5 rounded-sm", swatch)} aria-hidden />
            <Icon className="size-3.5 text-fg-subtle" aria-hidden />
            <span className="text-fg">{label}</span>
            {count > 1 && <span className="tabular-nums">×{count}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/** The page's blocks in reading order; hovering or focusing one rings its box. */
function BlockList({
  blocks,
  onActive,
}: {
  blocks: LayoutBlock[];
  onActive: (order: number | null) => void;
}) {
  if (blocks.length === 0) return <p className="text-sm text-fg-muted">No blocks on this page.</p>;
  return (
    <ol className="space-y-2" aria-label="Blocks in reading order">
      {blocks.map((block) => {
        const { label, Icon, border } = BLOCK_META[block.type];
        return (
          <li
            key={block.order}
            tabIndex={block.box ? 0 : undefined}
            onMouseEnter={() => onActive(block.order)}
            onMouseLeave={() => onActive(null)}
            onFocus={() => onActive(block.order)}
            onBlur={() => onActive(null)}
            className="rounded-xl bg-surface-2 px-3 py-2.5 outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <div className="flex items-center gap-2 text-xs font-medium text-fg-muted">
              <span
                className={cx(
                  "inline-grid size-5 shrink-0 place-items-center rounded border-2 bg-surface text-[10px] font-semibold text-fg tabular-nums",
                  border,
                )}
                aria-hidden
              >
                {block.order + 1}
              </span>
              <Icon className="size-3.5 text-fg-subtle" aria-hidden />
              <span className="text-fg">{label}</span>
            </div>
            <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed whitespace-pre-line text-fg-muted">
              {block.text}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The page image with the layout blocks drawn over it (PRD 0009 D11b). Scans have no
 * positions, so their blocks are listed only; a highlighted row ("Show on page") gets an
 * accent ring and is scrolled into view.
 */
export function PagePreview({
  documentId,
  layout,
  page,
  onPageChange,
  highlight,
}: {
  documentId: string;
  layout: LayoutResponse;
  page: number;
  onPageChange: (page: number) => void;
  highlight: PageHighlight | null;
}) {
  const [loaded, setLoaded] = useState<number | null>(null);
  const [failed, setFailed] = useState<number | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const mark = useRef<HTMLDivElement>(null);

  const blocks = layout.blocks.filter((block) => block.page === page);
  const positioned = blocks.some((block) => block.box !== null);
  const analysed = layout.pages.some((info) => info.page === page);
  const shownHighlight = highlight && highlight.page === page ? highlight : null;

  useEffect(() => {
    if (!shownHighlight || loaded !== page || !mark.current) return;
    mark.current.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [shownHighlight, loaded, page]);

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <figure className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <Legend layout={layout} page={page} />
          <PageSwitcher page={page} count={layout.page_count} onChange={onPageChange} />
        </div>
        <div
          className="relative mx-auto w-full max-w-2xl overflow-hidden rounded-lg border border-border bg-white shadow-card"
          style={{ aspectRatio: String(pageAspect(layout, page)) }}
        >
          {failed === page ? (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-fg-subtle">
              <span className="inline-flex flex-col items-center gap-2">
                <ImageOff className="size-6" aria-hidden />
                The page image could not be loaded.
              </span>
            </div>
          ) : (
            <>
              {loaded !== page && <Skeleton className="absolute inset-0 rounded-none" />}
              <img
                key={page}
                src={pageImageUrl(documentId, page)}
                alt={`Page ${page} of the document`}
                loading="lazy"
                onLoad={() => setLoaded(page)}
                onError={() => setFailed(page)}
                className="absolute inset-0 size-full object-contain"
              />
              {loaded === page && (
                <>
                  {blocks.map((block) => (
                    <BlockBox key={block.order} block={block} active={active === block.order} />
                  ))}
                  {shownHighlight && (
                    <div
                      ref={mark}
                      key={shownHighlight.nonce}
                      className="pointer-events-none absolute rounded-sm bg-highlight/50 ring-3 ring-accent flash-highlight"
                      style={boxStyle(shownHighlight.box, BLOCK_PAD / 2)}
                      role="img"
                      aria-label={`Highlighted: ${shownHighlight.label}`}
                    />
                  )}
                </>
              )}
            </>
          )}
        </div>
        <figcaption className="mt-2 text-center text-xs text-fg-subtle">
          {!analysed
            ? "This page was not analysed (beyond the vision page limit)."
            : positioned
              ? "Boxes show where each block was found, numbered in reading order."
              : "Scanned pages have no positions, so their blocks are listed instead of drawn."}
        </figcaption>
      </figure>
      <div className="min-w-0">
        <h3 className="mb-2 text-sm font-semibold text-fg">Blocks on page {page}</h3>
        <BlockList blocks={blocks} onActive={setActive} />
      </div>
    </div>
  );
}

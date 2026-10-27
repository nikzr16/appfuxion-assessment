import { ShieldX, TextSearch } from "lucide-react";

import type { FieldConfidence } from "../api/types.ts";
import { cx } from "../lib/cx.ts";
import { CONFIDENCE_LABEL, confidenceTooltip, formatScore, highlightOf } from "../lib/confidence.ts";
import { CONFIDENCE_STYLE } from "./confidenceStyle.ts";
import { Badge } from "./ui/Badge.tsx";

interface ConfidenceBadgeProps {
  confidence: FieldConfidence;
  /** Icon only (line-item cells); the label stays available to screen readers and the tooltip. */
  compact?: boolean;
  className?: string;
}

/** `High` / `Medium` / `Low` with its icon; score and reasons in the tooltip. */
export function ConfidenceBadge({ confidence, compact = false, className }: ConfidenceBadgeProps) {
  const { tone, Icon, text } = CONFIDENCE_STYLE[confidence.label];
  const label = CONFIDENCE_LABEL[confidence.label];
  const tooltip = confidenceTooltip(confidence);
  if (compact) {
    return (
      <span className={cx("inline-flex shrink-0", text, className)} title={tooltip}>
        <Icon className="size-4" aria-hidden />
        <span className="sr-only">
          {label} confidence, {formatScore(confidence.score)}. {confidence.reasons.join(". ")}
        </span>
      </span>
    );
  }
  return (
    <span title={tooltip} className={cx("inline-flex shrink-0", className)}>
      <Badge tone={tone} icon={<Icon className="size-3.5" aria-hidden />} className="px-2">
        {label}
        <span className="sr-only">
          {" "}
          confidence, {formatScore(confidence.score)}. {confidence.reasons.join(". ")}
        </span>
      </Badge>
    </span>
  );
}

/** "Not found in document" next to a value the grounding check could not find. */
export function NotFoundMarker({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-danger">
      <ShieldX className={cx("size-3.5", compact && "hidden")} aria-hidden />
      Not found in document
    </span>
  );
}

/** A small button that scrolls the raw text to where the value was found. */
export function ShowInTextButton({
  confidence,
  fieldLabel,
  onLocate,
}: {
  confidence: FieldConfidence;
  fieldLabel: string;
  onLocate: (span: { start: number; end: number }) => void;
}) {
  const span = highlightOf(confidence);
  if (!span) return null;
  const where = confidence.page !== null ? ` (page ${confidence.page})` : "";
  return (
    <button
      type="button"
      onClick={() => onLocate(span)}
      className="inline-grid size-6 shrink-0 place-items-center rounded-md text-fg-subtle hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      title={`Show in raw text${where}`}
      aria-label={`Show ${fieldLabel} in the raw text${where}`}
    >
      <TextSearch className="size-3.5" aria-hidden />
    </button>
  );
}

import { cx } from "../../lib/cx.ts";

/** Placeholder block shown while data loads; sized like the content so nothing jumps. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("animate-pulse rounded-md bg-surface-2", className)} />;
}

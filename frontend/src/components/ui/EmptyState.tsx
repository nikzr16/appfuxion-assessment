import type { ReactNode } from "react";

import { cx } from "../../lib/cx.ts";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** Render the title as the page's <h1> (for pages that are only this state). */
  pageHeading?: boolean;
}

export function EmptyState({ icon, title, description, action, className, pageHeading = false }: EmptyStateProps) {
  return (
    <div className={cx("flex flex-col items-center px-6 py-12 text-center", className)}>
      <span className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
        {icon}
      </span>
      {pageHeading ? (
        <h1 tabIndex={-1} className="mt-4 text-lg font-semibold text-fg outline-none">
          {title}
        </h1>
      ) : (
        <p className="mt-4 text-base font-semibold text-fg">{title}</p>
      )}
      {description && <p className="mt-1 max-w-sm text-sm text-fg-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

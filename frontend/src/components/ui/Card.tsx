import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx.ts";

export function Card({ className, children, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cx("rounded-2xl border border-border bg-surface shadow-card", className)}
      {...props}
    >
      {children}
    </section>
  );
}

interface CardHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  id?: string;
  className?: string;
}

export function CardHeader({ title, description, icon, actions, id, className }: CardHeaderProps) {
  return (
    <div className={cx("flex flex-wrap items-start justify-between gap-3 px-5 pt-5 sm:px-6", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h2 id={id} className="text-base font-semibold text-fg">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-fg-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("px-5 pt-4 pb-5 sm:px-6", className)}>{children}</div>;
}

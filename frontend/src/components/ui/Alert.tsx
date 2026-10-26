import { CircleAlert, CircleCheck, Info, RefreshCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "../../lib/cx.ts";
import { friendlyError } from "../../lib/errors.ts";
import { Button } from "./Button.tsx";

type AlertTone = "info" | "success" | "warning" | "danger";

const STYLES: Record<AlertTone, { box: string; icon: ReactNode }> = {
  info: { box: "border-info/30 bg-info-soft", icon: <Info className="size-5 text-info" aria-hidden /> },
  success: {
    box: "border-success/30 bg-success-soft",
    icon: <CircleCheck className="size-5 text-success" aria-hidden />,
  },
  warning: {
    box: "border-warning/30 bg-warning-soft",
    icon: <TriangleAlert className="size-5 text-warning" aria-hidden />,
  },
  danger: {
    box: "border-danger/30 bg-danger-soft",
    icon: <CircleAlert className="size-5 text-danger" aria-hidden />,
  },
};

interface AlertProps {
  tone?: AlertTone;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  role?: "alert" | "status";
}

/** Inline message next to the action that caused it (PRD D12). */
export function Alert({ tone = "info", title, children, action, className, role }: AlertProps) {
  const style = STYLES[tone];
  return (
    <div role={role} className={cx("flex gap-3 rounded-xl border p-4", style.box, className)}>
      <span className="mt-0.5 shrink-0">{style.icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-fg">{title}</p>
        {children && <div className="mt-1 text-sm break-words text-fg-muted">{children}</div>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

/** An error from a failed request, in friendly words, with an optional retry. */
export function ErrorAlert({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const { title, message } = friendlyError(error);
  return (
    <Alert
      tone="danger"
      role="alert"
      title={title}
      className={className}
      action={
        onRetry && (
          <Button variant="secondary" size="sm" icon={<RefreshCw className="size-4" aria-hidden />} onClick={onRetry}>
            Try again
          </Button>
        )
      }
    >
      {message}
    </Alert>
  );
}

import { CircleCheck, CircleX, LoaderCircle } from "lucide-react";

import type { DocumentStatus, Severity } from "../api/types.ts";
import { Badge } from "./ui/Badge.tsx";
import { SEVERITY_STYLE } from "./severity.tsx";

const STATUS = {
  processing: {
    tone: "accent",
    label: "Processing",
    icon: <LoaderCircle className="size-3.5 animate-spin" aria-hidden />,
  },
  completed: { tone: "success", label: "Completed", icon: <CircleCheck className="size-3.5" aria-hidden /> },
  failed: { tone: "danger", label: "Failed", icon: <CircleX className="size-3.5" aria-hidden /> },
} as const;

/** Document status: colour + icon + text (never colour alone). */
export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { tone, label, icon } = STATUS[status];
  return (
    <Badge tone={tone} icon={icon}>
      {label}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { tone, label, Icon } = SEVERITY_STYLE[severity];
  return (
    <Badge tone={tone} icon={<Icon className="size-3.5" aria-hidden />}>
      {label}
    </Badge>
  );
}

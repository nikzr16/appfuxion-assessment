import { CircleAlert, Info, TriangleAlert, type LucideIcon } from "lucide-react";

import type { Severity } from "../api/types.ts";
import type { Tone } from "./ui/Badge.tsx";

/** One visual language for validation severities across the detail page (PRD D8). */
export const SEVERITY_STYLE: Record<
  Severity,
  { tone: Tone; label: string; Icon: LucideIcon; text: string; ring: string; tint: string }
> = {
  error: {
    tone: "danger",
    label: "Error",
    Icon: CircleAlert,
    text: "text-danger",
    ring: "ring-2 ring-danger/60",
    tint: "bg-danger-soft",
  },
  warning: {
    tone: "warning",
    label: "Warning",
    Icon: TriangleAlert,
    text: "text-warning",
    ring: "ring-2 ring-warning/60",
    tint: "bg-warning-soft",
  },
  info: {
    tone: "info",
    label: "Info",
    Icon: Info,
    text: "text-info",
    ring: "ring-2 ring-info/50",
    tint: "bg-info-soft",
  },
};

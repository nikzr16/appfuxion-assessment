import { ShieldAlert, ShieldCheck, ShieldX, type LucideIcon } from "lucide-react";

import type { ConfidenceLabel } from "../api/types.ts";
import type { Tone } from "./ui/Badge.tsx";

/** One visual language for confidence (PRD 0008 D9): a distinct icon per level, never colour alone. */
export const CONFIDENCE_STYLE: Record<ConfidenceLabel, { tone: Tone; Icon: LucideIcon; text: string }> = {
  high: { tone: "success", Icon: ShieldCheck, text: "text-success" },
  medium: { tone: "warning", Icon: ShieldAlert, text: "text-warning" },
  low: { tone: "danger", Icon: ShieldX, text: "text-danger" },
};

import { useEffect, useState } from "react";

import { getHealth, type HealthResponse } from "../api/client.ts";
import { cx } from "../lib/cx.ts";

type State =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "unreachable" };

const DOTS = {
  loading: "bg-fg-subtle animate-pulse",
  ok: "bg-success",
  degraded: "bg-warning",
  unreachable: "bg-danger",
} as const;

function describe(state: State): { dot: keyof typeof DOTS; label: string; detail: string } {
  switch (state.kind) {
    case "loading":
      return { dot: "loading", label: "Checking…", detail: "Checking the backend" };
    case "unreachable":
      return { dot: "unreachable", label: "Offline", detail: "Backend unreachable" };
    case "ready":
      return state.health.status === "ok"
        ? { dot: "ok", label: "Online", detail: "Backend healthy, database ok" }
        : {
            dot: "degraded",
            label: "Degraded",
            detail: `Backend degraded, database ${state.health.database}`,
          };
  }
}

/** Compact backend status for the header; the full sentence is in the title and for screen readers. */
export default function HealthBadge() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled) setState({ kind: "ready", health });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { dot, label, detail } = describe(state);
  return (
    <span
      role="status"
      data-testid="health-badge"
      title={detail}
      className="inline-flex h-8 items-center gap-2 rounded-full border border-border bg-surface px-3 text-xs font-medium text-fg-muted"
    >
      <span className={cx("size-2 rounded-full", DOTS[dot])} aria-hidden />
      <span aria-hidden className="hidden sm:inline">
        {label}
      </span>
      <span className="sr-only">{detail}</span>
    </span>
  );
}

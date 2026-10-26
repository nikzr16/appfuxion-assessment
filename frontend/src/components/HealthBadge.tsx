import { useEffect, useState } from "react";

import { getHealth, type HealthResponse } from "../api/client.ts";

type State =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "unreachable" };

const STYLES = {
  loading: "bg-slate-100 text-slate-600 ring-slate-300",
  ok: "bg-emerald-50 text-emerald-700 ring-emerald-300",
  degraded: "bg-amber-50 text-amber-800 ring-amber-300",
  unreachable: "bg-red-50 text-red-700 ring-red-300",
} as const;

function describe(state: State): { style: keyof typeof STYLES; label: string } {
  switch (state.kind) {
    case "loading":
      return { style: "loading", label: "Checking backend..." };
    case "unreachable":
      return { style: "unreachable", label: "Backend unreachable" };
    case "ready":
      return state.health.status === "ok"
        ? { style: "ok", label: "Backend healthy - database ok" }
        : { style: "degraded", label: `Backend degraded - database ${state.health.database}` };
  }
}

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

  const { style, label } = describe(state);
  return (
    <span
      role="status"
      data-testid="health-badge"
      className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset ${STYLES[style]}`}
    >
      {label}
    </span>
  );
}

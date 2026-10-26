import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { cx } from "../../lib/cx.ts";
import {
  applyTheme,
  readThemePreference,
  saveThemePreference,
  watchSystemTheme,
  type ThemePreference,
} from "../../lib/theme.ts";

const OPTIONS: Array<{ value: ThemePreference; label: string; Icon: LucideIcon }> = [
  { value: "light", label: "Light theme", Icon: Sun },
  { value: "dark", label: "Dark theme", Icon: Moon },
  { value: "system", label: "System theme", Icon: Monitor },
];

/** System / Light / Dark switch, remembered in localStorage (PRD D13). */
export function ThemeToggle() {
  const [preference, setPreference] = useState<ThemePreference>(readThemePreference);

  useEffect(() => {
    applyTheme(preference);
    saveThemePreference(preference);
    if (preference !== "system") return;
    return watchSystemTheme(() => applyTheme("system"));
  }, [preference]);

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex h-8 items-center rounded-full border border-border bg-surface p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const checked = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={label}
            title={label}
            onClick={() => setPreference(value)}
            className={cx(
              "grid size-7 place-items-center rounded-full transition-colors",
              checked ? "bg-accent-soft text-accent" : "text-fg-subtle hover:text-fg",
            )}
          >
            <Icon className="size-4" aria-hidden />
          </button>
        );
      })}
    </div>
  );
}

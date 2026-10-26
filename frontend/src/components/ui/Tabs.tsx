import { useRef, type KeyboardEvent } from "react";

import { cx } from "../../lib/cx.ts";

export interface TabOption<T extends string> {
  value: T;
  label: string;
}

interface TabsProps<T extends string> {
  label: string;
  options: readonly TabOption<T>[];
  value: T;
  onChange: (value: T) => void;
  controls?: string;
}

/** Segmented tabs with arrow-key navigation (roving tabindex). */
export function Tabs<T extends string>({ label, options, value, onChange, controls }: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = options.length - 1;
    const next =
      event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (next === null) return;
    event.preventDefault();
    const option = options[next];
    if (!option) return;
    onChange(option.value);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex w-full gap-1 overflow-x-auto rounded-xl border border-border bg-surface-2 p-1 [scrollbar-width:none] sm:inline-flex sm:w-auto"
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(element) => {
              refs.current[index] = element;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={controls}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cx(
              "h-8 flex-1 rounded-lg px-2 text-sm font-medium whitespace-nowrap transition-colors sm:flex-none sm:px-3",
              selected ? "bg-surface text-fg shadow-sm" : "text-fg-muted hover:text-fg",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

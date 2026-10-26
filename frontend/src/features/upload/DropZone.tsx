import { CloudUpload } from "lucide-react";
import { useState, type ChangeEvent, type DragEvent } from "react";

import type { ClientConfig } from "../../api/types.ts";
import { cx } from "../../lib/cx.ts";
import { acceptAttribute, describeAccepted, MAX_FILES } from "../../lib/upload.ts";

interface DropZoneProps {
  config: ClientConfig;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}

/**
 * Drag-and-drop area. The real control is a visually hidden file input inside the label,
 * so Tab focuses it and Enter / Space open the picker (PRD D15).
 */
export function DropZone({ config, disabled = false, onFiles }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    onFiles(Array.from(event.dataTransfer.files));
  }

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    onFiles(Array.from(event.target.files ?? []));
    // Allow picking the same file again after removing it.
    event.target.value = "";
  }

  return (
    <label
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cx(
        "group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors sm:py-16",
        "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring",
        dragging
          ? "border-accent bg-accent-soft"
          : "border-border-strong bg-surface hover:border-accent/60 hover:bg-surface-2",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <input
        type="file"
        multiple
        accept={acceptAttribute(config)}
        disabled={disabled}
        onChange={onChange}
        className="sr-only"
        aria-describedby="dropzone-hint"
      />
      <span
        className={cx(
          "grid size-14 place-items-center rounded-2xl transition-transform",
          dragging ? "scale-110 bg-accent text-accent-fg" : "bg-accent-soft text-accent group-hover:scale-105",
        )}
      >
        <CloudUpload className="size-7" aria-hidden />
      </span>
      <span className="mt-4 text-base font-semibold text-fg">
        {dragging ? "Drop to add files" : "Drag & drop invoices or receipts"}
      </span>
      <span className="mt-1 text-sm text-fg-muted">
        or <span className="font-medium text-accent underline-offset-2 group-hover:underline">browse files</span>
      </span>
      <span id="dropzone-hint" className="mt-4 text-xs text-fg-subtle">
        {describeAccepted(config)} · up to {config.max_upload_mb} MB each · max {MAX_FILES} files
      </span>
    </label>
  );
}

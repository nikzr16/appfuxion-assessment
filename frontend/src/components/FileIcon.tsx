import { FileImage, FileText } from "lucide-react";

import { cx } from "../lib/cx.ts";

/** PDF → document icon, images → picture icon, in a soft tile. */
export function FileIcon({ contentType, className }: { contentType: string; className?: string }) {
  const Icon = contentType.startsWith("image/") ? FileImage : FileText;
  return (
    <span
      className={cx(
        "grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent",
        className,
      )}
    >
      <Icon className="size-5" aria-hidden />
    </span>
  );
}

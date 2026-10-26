import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "./Button.tsx";

interface CopyButtonProps {
  value: string;
  label: string;
  showLabel?: boolean;
}

/** Copies `value` to the clipboard and confirms with a check mark for a moment. */
export function CopyButton({ value, label, showLabel = false }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // Clipboard blocked (insecure context or permission): nothing useful to show.
    }
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={copy}
      aria-label={copied ? "Copied" : label}
      title={label}
      icon={
        copied ? (
          <Check className="size-4 text-success" aria-hidden />
        ) : (
          <Copy className="size-4" aria-hidden />
        )
      }
    >
      {showLabel && (copied ? "Copied" : "Copy")}
    </Button>
  );
}

import { ArrowRight, CircleCheck, CircleX, Clock, LoaderCircle, RotateCw, X } from "lucide-react";
import { Link } from "react-router";

import { FileIcon } from "../../components/FileIcon.tsx";
import { Badge } from "../../components/ui/Badge.tsx";
import { Button } from "../../components/ui/Button.tsx";
import { formatBytes } from "../../lib/format.ts";
import type { QueueItem } from "./useUploadQueue.ts";

const STATE_BADGE = {
  queued: { tone: "neutral", label: "Ready", icon: <Clock className="size-3.5" aria-hidden /> },
  uploading: {
    tone: "accent",
    label: "Uploading",
    icon: <LoaderCircle className="size-3.5 animate-spin" aria-hidden />,
  },
  uploaded: { tone: "success", label: "Uploaded", icon: <CircleCheck className="size-3.5" aria-hidden /> },
  rejected: { tone: "danger", label: "Not uploaded", icon: <CircleX className="size-3.5" aria-hidden /> },
} as const;

interface UploadQueueProps {
  items: QueueItem[];
  running: boolean;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}

export function UploadQueue({ items, running, onRemove, onRetry }: UploadQueueProps) {
  return (
    <ul aria-label="Files to upload" className="divide-y divide-border">
      {items.map((item) => {
        const badge = STATE_BADGE[item.state];
        const fileType = item.file.type || "application/pdf";
        return (
          <li key={item.id} className="flex items-start gap-3 py-3.5 first:pt-0 last:pb-0">
            <FileIcon contentType={fileType} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <p className="min-w-0 truncate text-sm font-medium text-fg" title={item.file.name}>
                  {item.file.name}
                </p>
                <Badge tone={badge.tone} icon={badge.icon}>
                  {badge.label}
                </Badge>
              </div>
              <p className="mt-0.5 text-xs text-fg-subtle tabular-nums">{formatBytes(item.file.size)}</p>
              {item.error && (
                <p className="mt-1.5 text-sm text-danger">
                  <span className="font-medium">{item.error.title}.</span> {item.error.message}
                </p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {item.state === "uploaded" && item.documentId && (
                <Link
                  to={`/documents/${item.documentId}`}
                  className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-sm font-medium text-accent hover:bg-accent-soft"
                >
                  View
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              )}
              {item.state === "rejected" && !item.clientRejected && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={running}
                  onClick={() => onRetry(item.id)}
                  icon={<RotateCw className="size-4" aria-hidden />}
                >
                  Try again
                </Button>
              )}
              {item.state !== "uploading" && item.state !== "uploaded" && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={running}
                  aria-label={`Remove ${item.file.name}`}
                  onClick={() => onRemove(item.id)}
                >
                  <X className="size-4" aria-hidden />
                </Button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

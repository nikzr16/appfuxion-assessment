/** Client-side checks run before a file is sent (PRD D5). The server checks again. */
import type { ClientConfig } from "../api/types.ts";

export const MAX_FILES = 5;

const EXTENSIONS: Record<string, string[]> = {
  "application/pdf": [".pdf"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
};

const LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "image/jpeg": "JPG",
  "image/png": "PNG",
};

/** Used until `GET /api/config` answers, or when it fails. */
export const DEFAULT_CONFIG: ClientConfig = {
  max_upload_mb: 10,
  accepted_content_types: ["application/pdf", "image/jpeg", "image/png"],
  base_currency: "MYR",
};

export function acceptAttribute(config: ClientConfig): string {
  return config.accepted_content_types
    .flatMap((type) => [...(EXTENSIONS[type] ?? []), type])
    .join(",");
}

/** `PDF, JPG or PNG` */
export function describeAccepted(config: ClientConfig): string {
  const labels = config.accepted_content_types.map((type) => LABELS[type] ?? type);
  if (labels.length < 2) return labels[0] ?? "";
  return `${labels.slice(0, -1).join(", ")} or ${labels.at(-1)}`;
}

export interface FileProblem {
  code: "empty" | "type" | "size";
  message: string;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export function checkFile(file: File, config: ClientConfig): FileProblem | null {
  const extension = extensionOf(file.name);
  const extensionOk = config.accepted_content_types.some((type) =>
    (EXTENSIONS[type] ?? []).includes(extension),
  );
  // Some systems report no MIME type at all; then the extension decides and the server sniffs.
  const mimeOk = file.type === "" || config.accepted_content_types.includes(file.type);
  if (!extensionOk || !mimeOk) {
    return { code: "type", message: `Not a supported file. Use ${describeAccepted(config)}.` };
  }
  if (file.size === 0) return { code: "empty", message: "This file is empty." };
  if (file.size > config.max_upload_mb * 1024 * 1024) {
    return { code: "size", message: `Larger than the ${config.max_upload_mb} MB limit.` };
  }
  return null;
}

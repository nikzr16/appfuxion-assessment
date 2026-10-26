/** Typed fetch wrapper for the backend API. All calls go through `request`. */

import type {
  AgentResult,
  AgentRunRead,
  ClientConfig,
  DocumentList,
  DocumentRead,
  DocumentStatus,
  DocumentTextResponse,
  DocumentTrace,
  DocumentUploadResponse,
  ExtractionResponse,
  MetricsSummary,
} from "./types.ts";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

/** Error body shape returned by every backend error: `{"error": {"code", "message"}}`. */
export interface ApiErrorBody {
  error: { code: string; message: string };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: unknown;

  constructor(status: number, code: string, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (error) {
    // fetch only rejects when no HTTP answer arrived (offline, DNS, proxy down).
    throw new ApiError(0, "network_error", "Cannot reach the server.", error);
  }

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    if (isApiErrorBody(body)) {
      throw new ApiError(response.status, body.error.code, body.error.message, body);
    }
    throw new ApiError(response.status, "http_error", `Request failed (${response.status})`, body);
  }
  return body as T;
}

// -- Health ------------------------------------------------------------------------

export interface HealthResponse {
  status: "ok" | "degraded";
  database: "ok" | "error";
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) return false;
  const { status, database } = value as { status?: unknown; database?: unknown };
  return (status === "ok" || status === "degraded") && (database === "ok" || database === "error");
}

/**
 * `GET /api/health`. The backend answers 503 with the same body when the database is
 * down, so that case is returned as data rather than thrown.
 */
export async function getHealth(): Promise<HealthResponse> {
  try {
    return await request<HealthResponse>("/health");
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && isHealthResponse(error.body)) {
      return error.body;
    }
    throw error;
  }
}

// -- Config ------------------------------------------------------------------------

/** `GET /api/config`: upload limits and display settings from the backend. */
export function getConfig(): Promise<ClientConfig> {
  return request<ClientConfig>("/config");
}

// -- Documents ---------------------------------------------------------------------

/** `POST /api/documents` with multipart field `file`; processing starts in the background. */
export function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const body = new FormData();
  body.append("file", file);
  // No Content-Type header: the browser sets multipart/form-data with its boundary.
  return request<DocumentUploadResponse>("/documents", { method: "POST", body });
}

export interface ListDocumentsParams {
  limit: number;
  offset: number;
  status?: DocumentStatus;
}

/** `GET /api/documents`, newest first. */
export function listDocuments({ limit, offset, status }: ListDocumentsParams): Promise<DocumentList> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) query.set("status", status);
  return request<DocumentList>(`/documents?${query.toString()}`);
}

export function getDocument(id: string): Promise<DocumentRead> {
  return request<DocumentRead>(`/documents/${encodeURIComponent(id)}`);
}

/** `GET /api/documents/{id}/result`; 409 `result_not_ready` / `result_unavailable` are thrown. */
export function getResult(id: string): Promise<AgentResult> {
  return request<AgentResult>(`/documents/${encodeURIComponent(id)}/result`);
}

/** Runs a read whose 409 means "nothing saved yet" and returns `null` in that case. */
async function nullOnConflict<T>(read: Promise<T>): Promise<T | null> {
  try {
    return await read;
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) return null;
    throw error;
  }
}

/** Saved structured data, or `null` when none exists (409 `extraction_*`). */
export function getExtraction(id: string): Promise<ExtractionResponse | null> {
  return nullOnConflict(request<ExtractionResponse>(`/documents/${encodeURIComponent(id)}/extraction`));
}

/** Saved raw text, or `null` when none exists (409 `text_*`). */
export function getText(id: string): Promise<DocumentTextResponse | null> {
  return nullOnConflict(request<DocumentTextResponse>(`/documents/${encodeURIComponent(id)}/text`));
}

/** `GET /api/documents/{id}/runs`, newest first, each with its tool-call steps. */
export function getRuns(id: string): Promise<AgentRunRead[]> {
  return request<AgentRunRead[]>(`/documents/${encodeURIComponent(id)}/runs`);
}

/** `POST /api/documents/{id}/reprocess`; 409 `already_processing` is thrown. */
export function reprocessDocument(id: string): Promise<DocumentUploadResponse> {
  return request<DocumentUploadResponse>(`/documents/${encodeURIComponent(id)}/reprocess`, {
    method: "POST",
  });
}

// -- Observability (0007) ------------------------------------------------------------

/** `GET /api/documents/{id}/trace`: the latest run, or `runId`. */
export function getTrace(id: string, runId?: string): Promise<DocumentTrace> {
  const query = runId ? `?${new URLSearchParams({ run_id: runId }).toString()}` : "";
  return request<DocumentTrace>(`/documents/${encodeURIComponent(id)}/trace${query}`);
}

/** `GET /api/metrics/summary`: all time, or the last `days` days. */
export function getMetrics(days?: number): Promise<MetricsSummary> {
  const query = days ? `?${new URLSearchParams({ days: String(days) }).toString()}` : "";
  return request<MetricsSummary>(`/metrics/summary${query}`);
}

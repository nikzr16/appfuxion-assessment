/** Typed fetch wrapper for the backend API. All calls go through `request`. */

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
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });

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

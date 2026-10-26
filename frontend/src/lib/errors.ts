import { ApiError } from "../api/client.ts";

export interface FriendlyError {
  title: string;
  message: string;
}

const MESSAGES: Record<string, (error: ApiError) => FriendlyError> = {
  network_error: () => ({
    title: "Can't reach the server",
    message: "Check your connection and that the backend is running, then try again.",
  }),
  unsupported_media_type: () => ({
    title: "Unsupported file type",
    message: "Only PDF, JPG and PNG files can be processed.",
  }),
  payload_too_large: (error) => ({ title: "File too large", message: error.message }),
  validation_failed: (error) => ({ title: "Upload rejected", message: error.message }),
  llm_not_configured: () => ({
    title: "AI processing isn't configured",
    message:
      "The server has no OpenAI API key (OPENAI_API_KEY), so documents can't be processed. Ask the administrator to set it.",
  }),
  already_processing: () => ({
    title: "Already processing",
    message: "This document is already being processed. The page updates when it finishes.",
  }),
  not_found: () => ({
    title: "Not found",
    message: "This document doesn't exist or was removed.",
  }),
  internal_error: () => ({
    title: "Something went wrong",
    message: "The server hit an unexpected error. Please try again.",
  }),
};

/** Turns any thrown value into a short title and a sentence a user can act on (PRD D12). */
export function friendlyError(error: unknown): FriendlyError {
  if (error instanceof ApiError) {
    const build = MESSAGES[error.code];
    if (build) return build(error);
    return { title: "Request failed", message: error.message };
  }
  return {
    title: "Something went wrong",
    message: "An unexpected error occurred. Please try again.",
  };
}

/** 404, or 422 for an id that is not a UUID: either way the document does not exist. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 422);
}

export function isNetworkError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "network_error";
}

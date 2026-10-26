import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client.ts";
import { friendlyError, isNetworkError, isNotFound } from "./errors.ts";

describe("friendlyError", () => {
  it("explains a missing OpenAI key", () => {
    const error = new ApiError(502, "llm_not_configured", "OPENAI_API_KEY is not set", null);
    expect(friendlyError(error)).toEqual({
      title: "AI processing isn't configured",
      message: expect.stringContaining("OPENAI_API_KEY") as string,
    });
  });

  it("keeps the server's message where it carries the detail", () => {
    const error = new ApiError(413, "payload_too_large", "File is larger than 10 MB.", null);
    expect(friendlyError(error)).toEqual({ title: "File too large", message: "File is larger than 10 MB." });
  });

  it("falls back to the server message, then to a generic one", () => {
    expect(friendlyError(new ApiError(418, "teapot", "I am a teapot", null))).toEqual({
      title: "Request failed",
      message: "I am a teapot",
    });
    expect(friendlyError(new Error("boom")).title).toBe("Something went wrong");
  });

  it("classifies not found and network errors", () => {
    expect(isNotFound(new ApiError(404, "not_found", "", null))).toBe(true);
    expect(isNotFound(new ApiError(422, "validation_failed", "", null))).toBe(true);
    expect(isNotFound(new ApiError(500, "internal_error", "", null))).toBe(false);
    expect(isNetworkError(new ApiError(0, "network_error", "", null))).toBe(true);
  });
});

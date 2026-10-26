import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, request } from "./client.ts";

describe("request", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("maps the backend error shape onto ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "not_found", message: "no such doc" } }), {
          status: 404,
        }),
      ),
    );

    const error = await request("/documents/doc_x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: "not_found", message: "no such doc" });
  });

  it("falls back to a generic error for non-JSON failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 502 })));

    await expect(request("/health")).rejects.toMatchObject({ status: 502, code: "http_error" });
  });
});

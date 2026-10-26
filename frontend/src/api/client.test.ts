import { afterEach, describe, expect, it, vi } from "vitest";

import { apiError, mockApi, ok } from "../test/fetchMock.ts";
import { pdfFile } from "../test/fixtures.ts";
import {
  ApiError,
  getConfig,
  getExtraction,
  getText,
  listDocuments,
  reprocessDocument,
  request,
  uploadDocument,
} from "./client.ts";

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

describe("endpoint functions", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uploads multipart field `file` without setting Content-Type", async () => {
    const api = mockApi({ "POST /documents": ok({ document_id: "d1", status: "processing" }, 202) });

    await expect(uploadDocument(pdfFile("a.pdf"))).resolves.toEqual({ document_id: "d1", status: "processing" });

    const [call] = api.callsTo("POST /documents");
    expect(call?.body).toBeInstanceOf(FormData);
    expect((call?.body as FormData).get("file")).toBeInstanceOf(File);
    expect(call?.headers["content-type"]).toBeUndefined();
  });

  it("sends limit, offset and status to the list", async () => {
    const api = mockApi({ "GET /documents": ok({ items: [], total: 0, limit: 20, offset: 40 }) });

    await listDocuments({ limit: 20, offset: 40, status: "failed" });

    expect(api.calls[0]?.url).toBe("/api/documents?limit=20&offset=40&status=failed");
  });

  it("turns a 409 on text / extraction into null", async () => {
    mockApi({
      "GET /documents/d1/text": apiError(409, "text_not_ready"),
      "GET /documents/d1/extraction": apiError(409, "extraction_unavailable"),
    });

    await expect(getText("d1")).resolves.toBeNull();
    await expect(getExtraction("d1")).resolves.toBeNull();
  });

  it("still throws other errors from text / extraction", async () => {
    mockApi({ "GET /documents/d1/text": apiError(404, "not_found") });

    await expect(getText("d1")).rejects.toMatchObject({ status: 404, code: "not_found" });
  });

  it("maps a failed fetch to a network_error ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getConfig()).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("throws the 409 of a reprocess that is already running", async () => {
    mockApi({ "POST /documents/d1/reprocess": apiError(409, "already_processing") });

    await expect(reprocessDocument("d1")).rejects.toMatchObject({ code: "already_processing" });
  });
});

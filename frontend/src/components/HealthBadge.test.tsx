import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HealthBadge from "./HealthBadge.tsx";

function mockFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("HealthBadge", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a healthy badge when the backend reports ok", async () => {
    const fetchMock = mockFetch(200, { status: "ok", database: "ok" });

    render(<HealthBadge />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking the backend");
    expect(await screen.findByText("Backend healthy, database ok")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("shows degraded when the backend answers 503", async () => {
    mockFetch(503, { status: "degraded", database: "error" });

    render(<HealthBadge />);

    expect(await screen.findByText("Backend degraded, database error")).toBeInTheDocument();
  });

  it("shows unreachable when a proxy answers 503 with a non-health body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Service Unavailable", { status: 503 })));

    render(<HealthBadge />);

    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
  });

  it("shows unreachable when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<HealthBadge />);

    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
  });
});

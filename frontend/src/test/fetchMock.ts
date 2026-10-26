/**
 * Route-based `fetch` stub for tests. Keys are `"METHOD /path"` (path without `/api` and
 * without the query string). A value can be one response, a sequence (each call takes the
 * next; the last one repeats), or a function of the call. Unmatched calls answer 404.
 */
import { vi } from "vitest";

export interface MockResponse {
  status: number;
  body?: unknown;
  /** Resolve the response only when this promise settles (to hold a request in flight). */
  wait?: Promise<unknown>;
}

export interface FetchCall {
  method: string;
  path: string;
  url: string;
  body: BodyInit | null | undefined;
  headers: Record<string, string>;
}

type RouteValue = MockResponse | MockResponse[] | ((call: FetchCall) => MockResponse);

export function ok(body: unknown, status = 200): MockResponse {
  return { status, body };
}

export function apiError(status: number, code: string, message = code): MockResponse {
  return { status, body: { error: { code, message } } };
}

export function mockApi(routes: Record<string, RouteValue>) {
  const calls: FetchCall[] = [];
  const counters = new Map<string, number>();

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.replace(/^\/api/, "").split("?")[0] ?? "";
    const call: FetchCall = {
      method,
      path,
      url,
      body: init?.body,
      headers: Object.fromEntries(new Headers(init?.headers).entries()),
    };
    calls.push(call);

    const key = `${method} ${path}`;
    const route = routes[key];
    let spec: MockResponse;
    if (route === undefined) spec = apiError(404, "not_found", `Unmocked ${key}`);
    else if (typeof route === "function") spec = route(call);
    else if (Array.isArray(route)) {
      const index = counters.get(key) ?? 0;
      counters.set(key, index + 1);
      spec = route[Math.min(index, route.length - 1)] as MockResponse;
    } else spec = route;

    if (spec.wait) await spec.wait;
    return new Response(spec.body === undefined ? null : JSON.stringify(spec.body), {
      status: spec.status,
      headers: { "Content-Type": "application/json" },
    });
  });

  vi.stubGlobal("fetch", fetchMock);

  return {
    calls,
    fetchMock,
    /** Calls matching `"METHOD /path"`. */
    callsTo(key: string): FetchCall[] {
      return calls.filter((call) => `${call.method} ${call.path}` === key);
    },
  };
}

/** A promise you resolve from the test, to keep a mocked request pending. */
export function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

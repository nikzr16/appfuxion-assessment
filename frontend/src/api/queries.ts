/**
 * TanStack Query hooks over the API client (PRD D2, D3). Components read server data only
 * through these hooks. Polling: every POLL_INTERVAL_MS while a document is processing;
 * TanStack Query skips intervals while the tab is hidden and refetches when it is visible.
 */
import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { DEFAULT_CONFIG } from "../lib/upload.ts";
import {
  ApiError,
  getConfig,
  getDocument,
  getExtraction,
  getLayout,
  getMetrics,
  getResult,
  getRuns,
  getText,
  getTrace,
  listDocuments,
  reprocessDocument,
  uploadDocument,
} from "./client.ts";
import type { ClientConfig, DocumentRead, DocumentStatus } from "./types.ts";

export const POLL_INTERVAL_MS = 10_000;
export const PAGE_SIZE = 20;

export const queryKeys = {
  config: ["config"] as const,
  documents: ["documents"] as const,
  documentPage: (status: DocumentStatus | undefined, page: number) =>
    ["documents", status ?? "all", page] as const,
  document: (id: string) => ["document", id] as const,
  result: (id: string) => ["result", id] as const,
  runs: (id: string) => ["runs", id] as const,
  text: (id: string) => ["text", id] as const,
  extraction: (id: string) => ["extraction", id] as const,
  layout: (id: string) => ["layout", id] as const,
  traces: (id: string) => ["trace", id] as const,
  trace: (id: string, runId: string | undefined) => ["trace", id, runId ?? "latest"] as const,
  metrics: (days: number | undefined) => ["metrics", days ?? "all"] as const,
};

/** Only network failures and server errors are worth retrying; 4xx answers are final. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return (error.status === 0 || error.status >= 500) && failureCount < 3;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
}

/** Upload limits from `GET /api/config`; the defaults until it answers or if it fails (D5). */
export function useClientConfig(): ClientConfig {
  const query = useQuery({
    queryKey: queryKeys.config,
    queryFn: getConfig,
    staleTime: Infinity,
    retry: 1,
  });
  return query.data ?? DEFAULT_CONFIG;
}

export function useDocuments(status: DocumentStatus | undefined, page: number) {
  return useQuery({
    queryKey: queryKeys.documentPage(status, page),
    queryFn: () => listDocuments({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, status }),
    placeholderData: (previous) => previous,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === "processing")
        ? POLL_INTERVAL_MS
        : false,
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: queryKeys.document(id),
    queryFn: () => getDocument(id),
    refetchInterval: (query) =>
      query.state.data?.status === "processing" ? POLL_INTERVAL_MS : false,
  });
}

export function useRuns(id: string, { live }: { live: boolean }) {
  return useQuery({
    queryKey: queryKeys.runs(id),
    queryFn: () => getRuns(id),
    refetchInterval: live ? POLL_INTERVAL_MS : false,
  });
}

/** The run's trace (PRD 0007 D6); polled with the runs while the document is processing. */
export function useTrace(id: string, runId: string | undefined, { live }: { live: boolean }) {
  return useQuery({
    queryKey: queryKeys.trace(id, runId),
    queryFn: () => getTrace(id, runId),
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === id ? previous : undefined,
    refetchInterval: live ? POLL_INTERVAL_MS : false,
  });
}

export function useMetrics(days: number | undefined) {
  return useQuery({
    queryKey: queryKeys.metrics(days),
    queryFn: () => getMetrics(days),
    placeholderData: (previous) => previous,
  });
}

export function useResult(id: string, { enabled }: { enabled: boolean }) {
  return useQuery({
    queryKey: queryKeys.result(id),
    queryFn: () => getResult(id),
    enabled,
    staleTime: Infinity,
  });
}

export function useText(id: string, { enabled }: { enabled: boolean }) {
  return useQuery({ queryKey: queryKeys.text(id), queryFn: () => getText(id), enabled });
}

export function useExtraction(id: string, { enabled }: { enabled: boolean }) {
  return useQuery({
    queryKey: queryKeys.extraction(id),
    queryFn: () => getExtraction(id),
    enabled,
  });
}

/** The newest tables-and-layout analysis (feature 0009); `null` when there is none. */
export function useLayout(id: string, { enabled }: { enabled: boolean }) {
  return useQuery({ queryKey: queryKeys.layout(id), queryFn: () => getLayout(id), enabled });
}

/**
 * When a document leaves `processing`, fetch its final runs, result and saved data once,
 * and refresh the list so its row shows the new status.
 */
export function useRefreshOnFinish(id: string, status: DocumentStatus | undefined): void {
  const queryClient = useQueryClient();
  const previous = useRef(status);
  useEffect(() => {
    if (previous.current === "processing" && status && status !== "processing") {
      for (const key of [
        queryKeys.runs(id),
        queryKeys.traces(id),
        queryKeys.result(id),
        queryKeys.text(id),
        queryKeys.extraction(id),
        queryKeys.layout(id),
        queryKeys.documents,
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    }
    previous.current = status;
  }, [id, status, queryClient]);
}

/** Shows a document as processing again right away (after reprocess, or a 409 saying so). */
export function markProcessing(queryClient: QueryClient, id: string): void {
  queryClient.setQueryData<DocumentRead>(queryKeys.document(id), (old) =>
    old ? { ...old, status: "processing", error: null } : old,
  );
  queryClient.removeQueries({ queryKey: queryKeys.result(id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.runs(id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.traces(id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
}

export function useUploadDocument() {
  return useMutation({ mutationFn: (file: File) => uploadDocument(file) });
}

export function useReprocess(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => reprocessDocument(id),
    onSuccess: () => markProcessing(queryClient, id),
  });
}

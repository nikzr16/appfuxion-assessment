/**
 * Upload queue (PRD D4): up to MAX_FILES files, checked on the client, sent as separate
 * `POST /documents` requests two at a time. When a run ends with every file accepted the
 * app goes to the documents list; otherwise the page stays and shows what failed.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { queryKeys, useClientConfig, useUploadDocument } from "../../api/queries.ts";
import { useAnnounce } from "../../components/ui/announce.ts";
import { friendlyError, type FriendlyError } from "../../lib/errors.ts";
import { checkFile, MAX_FILES } from "../../lib/upload.ts";

export const UPLOAD_CONCURRENCY = 2;

export type ItemState = "queued" | "uploading" | "uploaded" | "rejected";

export interface QueueItem {
  id: string;
  file: File;
  state: ItemState;
  error: FriendlyError | null;
  /** Rejected by the client checks: retrying cannot help, only removing. */
  clientRejected: boolean;
  documentId: string | null;
}

type Action =
  | { type: "add"; items: QueueItem[] }
  | { type: "update"; id: string; patch: Partial<QueueItem> }
  | { type: "remove"; id: string }
  | { type: "clear" };

function reducer(items: QueueItem[], action: Action): QueueItem[] {
  switch (action.type) {
    case "add":
      return [...items, ...action.items];
    case "update":
      return items.map((item) => (item.id === action.id ? { ...item, ...action.patch } : item));
    case "remove":
      return items.filter((item) => item.id !== action.id);
    case "clear":
      return [];
  }
}

let nextId = 0;

export interface UploadedState {
  uploaded: string[];
}

export function useUploadQueue() {
  const config = useClientConfig();
  const { mutateAsync } = useUploadDocument();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const announce = useAnnounce();

  const [items, dispatch] = useReducer(reducer, []);
  const [notice, setNotice] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const itemsRef = useRef(items);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const add = useCallback(
    (files: readonly File[]) => {
      if (files.length === 0) return;
      const open = itemsRef.current.filter((item) => item.state !== "uploaded").length;
      if (open + files.length > MAX_FILES) {
        const message = `You can upload up to ${MAX_FILES} files at a time.`;
        setNotice(message);
        announce(message);
        return;
      }
      setNotice(null);
      const added = files.map((file): QueueItem => {
        const problem = checkFile(file, config);
        return {
          id: `upload-${++nextId}`,
          file,
          state: problem ? "rejected" : "queued",
          error: problem ? { title: "Can't upload this file", message: problem.message } : null,
          clientRejected: problem !== null,
          documentId: null,
        };
      });
      dispatch({ type: "add", items: added });
      const rejected = added.filter((item) => item.clientRejected).length;
      announce(
        `${added.length - rejected} file${added.length - rejected === 1 ? "" : "s"} ready to upload` +
          (rejected ? `, ${rejected} not supported` : ""),
      );
    },
    [announce, config],
  );

  const run = useCallback(
    async (targets: QueueItem[]) => {
      if (targets.length === 0) return;
      setRunning(true);
      setNotice(null);
      const otherRejected = itemsRef.current.some(
        (item) => item.state === "rejected" && !targets.includes(item),
      );
      let cursor = 0;
      let failures = 0;
      const uploaded: string[] = [];

      const worker = async () => {
        while (cursor < targets.length) {
          const item = targets[cursor++];
          if (!item) break;
          dispatch({ type: "update", id: item.id, patch: { state: "uploading", error: null } });
          try {
            const response = await mutateAsync(item.file);
            uploaded.push(response.document_id);
            dispatch({
              type: "update",
              id: item.id,
              patch: { state: "uploaded", documentId: response.document_id },
            });
          } catch (error) {
            failures += 1;
            dispatch({ type: "update", id: item.id, patch: { state: "rejected", error: friendlyError(error) } });
          }
        }
      };
      await Promise.all(
        Array.from({ length: Math.min(UPLOAD_CONCURRENCY, targets.length) }, () => worker()),
      );

      setRunning(false);
      if (uploaded.length) void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      if (failures === 0 && !otherRejected) {
        announce(`${uploaded.length} file${uploaded.length === 1 ? "" : "s"} uploaded. Processing has started.`);
        const state: UploadedState = { uploaded };
        navigate("/documents", { state });
      } else {
        announce(`${uploaded.length} uploaded, ${failures} failed.`);
      }
    },
    [announce, mutateAsync, navigate, queryClient],
  );

  const upload = useCallback(() => {
    void run(itemsRef.current.filter((item) => item.state === "queued"));
  }, [run]);

  const retry = useCallback(
    (id: string) => {
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (item && item.state === "rejected" && !item.clientRejected) void run([item]);
    },
    [run],
  );

  const remove = useCallback((id: string) => {
    setNotice(null);
    dispatch({ type: "remove", id });
  }, []);

  const clear = useCallback(() => {
    setNotice(null);
    dispatch({ type: "clear" });
  }, []);

  return { items, notice, running, config, add, upload, retry, remove, clear };
}

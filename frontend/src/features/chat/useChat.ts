/**
 * Ask AI chat state (PRD 0010 D8, D11): one conversation, kept while the user moves between
 * pages and restored after a reload from its ID in sessionStorage. "New chat" forgets it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client.ts";
import { useAsk, useConversation } from "../../api/queries.ts";
import type { QueryTurn } from "../../api/types.ts";
import { readStoredConversation, storeConversation } from "../../lib/chat.ts";

export type ChatEntry =
  | { key: string; state: "pending"; question: string }
  | { key: string; state: "error"; question: string; error: unknown }
  | { key: string; state: "done"; question: string; turn: QueryTurn };

let nextKey = 0;
const newKey = () => `entry-${(nextKey += 1)}`;

function fromTurn(turn: QueryTurn): ChatEntry {
  if (turn.status === "completed") {
    return { key: turn.turn_id, state: "done", question: turn.question, turn };
  }
  const error = new ApiError(502, turn.error_code ?? "query_failed", turn.error ?? "No answer.", null);
  return { key: turn.turn_id, state: "error", question: turn.question, error };
}

export interface Chat {
  entries: ChatEntry[];
  pending: boolean;
  restoring: boolean;
  ask: (question: string) => void;
  retry: (key: string) => void;
  reset: () => void;
}

export function useChat({ open, documentId }: { open: boolean; documentId: string | undefined }): Chat {
  const [conversationId, setConversationId] = useState<string | null>(readStoredConversation);
  // The stored conversation whose turns are shown before the new ones (null after New chat).
  const [restoreId, setRestoreId] = useState<string | null>(conversationId);
  const [added, setAdded] = useState<ChatEntry[]>([]);
  const mutation = useAsk();
  const conversation = useConversation(restoreId, { enabled: open });
  // The newest chat wins: answers to a chat that was cleared meanwhile are dropped.
  const generation = useRef(0);

  const gone = conversation.error instanceof ApiError && conversation.error.status === 404;
  useEffect(() => {
    if (gone) storeConversation(null);
  }, [gone]);

  const restored = useMemo(
    () => (restoreId !== null && conversation.data ? conversation.data.turns.map(fromTurn) : []),
    [restoreId, conversation.data],
  );
  const entries = useMemo(() => [...restored, ...added], [restored, added]);
  const activeId = gone && conversationId === restoreId ? null : conversationId;

  const send = useCallback(
    (question: string, key: string) => {
      const ticket = generation.current;
      setAdded((list) => [...list.filter((entry) => entry.key !== key), { key, state: "pending", question }]);
      mutation.mutate(
        { question, conversation_id: activeId, document_id: documentId ?? null },
        {
          onSuccess: (response) => {
            if (ticket !== generation.current) return;
            setConversationId(response.conversation_id);
            storeConversation(response.conversation_id);
            setAdded((list) =>
              list.map((entry) => (entry.key === key ? { key, state: "done", question, turn: response } : entry)),
            );
          },
          onError: (error) => {
            if (ticket !== generation.current) return;
            setAdded((list) =>
              list.map((entry) => (entry.key === key ? { key, state: "error", question, error } : entry)),
            );
          },
        },
      );
    },
    [activeId, documentId, mutation],
  );

  const ask = useCallback((question: string) => send(question.trim(), newKey()), [send]);

  const retry = useCallback(
    (key: string) => {
      const entry = entries.find((item) => item.key === key);
      if (!entry) return;
      // A restored failed turn stays as it was; the retry is a new entry.
      send(entry.question, added.some((item) => item.key === key) ? key : newKey());
    },
    [entries, added, send],
  );

  const reset = useCallback(() => {
    generation.current += 1;
    mutation.reset();
    storeConversation(null);
    setConversationId(null);
    setRestoreId(null);
    setAdded([]);
  }, [mutation]);

  return {
    entries,
    pending: mutation.isPending,
    restoring: open && restoreId !== null && !gone && conversation.isPending,
    ask,
    retry,
    reset,
  };
}

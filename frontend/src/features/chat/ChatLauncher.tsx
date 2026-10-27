import { Sparkles } from "lucide-react";
import { lazy, Suspense, useRef, useState } from "react";
import { useLocation } from "react-router";

import { documentIdFromPath } from "../../lib/chat.ts";
import { useChat } from "./useChat.ts";

// Loaded on the first open: most visits never open the chat.
const ChatPanel = lazy(() => import("./ChatPanel.tsx").then((module) => ({ default: module.ChatPanel })));

/**
 * The floating "Ask AI" button on every page (PRD 0010 D11). The chat lives here, so it
 * survives page changes; on a document page, questions carry that document as context.
 */
export function ChatLauncher() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const documentId = documentIdFromPath(pathname);
  const chat = useChat({ open, documentId });
  const button = useRef<HTMLButtonElement>(null);

  const close = () => {
    setOpen(false);
    requestAnimationFrame(() => button.current?.focus());
  };

  return (
    <>
      {open && (
        <Suspense fallback={null}>
          <ChatPanel chat={chat} documentId={documentId} onClose={close} />
        </Suspense>
      )}
      <button
        ref={button}
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Ask AI about your invoices"
        aria-haspopup="dialog"
        hidden={open}
        className="fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 inline-flex size-14 items-center justify-center gap-2 rounded-full bg-accent text-sm font-semibold text-accent-fg shadow-lg ring-1 ring-black/5 transition hover:bg-accent-hover focus-visible:ring-4 focus-visible:ring-ring sm:size-auto sm:h-12 sm:px-5"
      >
        <Sparkles className="size-5" aria-hidden />
        <span className="hidden sm:inline">Ask AI</span>
        {chat.pending && (
          <span className="absolute top-1 right-1 size-2.5 rounded-full bg-warning ring-2 ring-surface" aria-hidden />
        )}
      </button>
    </>
  );
}

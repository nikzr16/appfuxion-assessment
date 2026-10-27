import { ArrowUp, FileText, MessageSquarePlus, Sparkles, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { useSuggestions } from "../../api/queries.ts";
import { Skeleton } from "../../components/ui/Skeleton.tsx";
import { canAsk, COUNTER_FROM, QUESTION_MAX } from "../../lib/chat.ts";
import { cx } from "../../lib/cx.ts";
import { AnswerCard, ErrorBubble, ThinkingBubble, UserBubble } from "./ChatMessages.tsx";
import type { Chat } from "./useChat.ts";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function useIsNarrow(): boolean {
  const query = "(max-width: 639px)";
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return narrow;
}

function Suggestions({
  documentId,
  onPick,
}: {
  documentId: string | undefined;
  onPick: (question: string) => void;
}) {
  const suggestions = useSuggestions(documentId, { enabled: true });
  const empty = suggestions.data?.indexed_documents === 0;
  return (
    <div className="flex flex-1 flex-col justify-end gap-4 pb-1">
      <div className="text-center">
        <span className="mx-auto grid size-11 place-items-center rounded-2xl bg-accent-soft text-accent">
          <Sparkles className="size-5" aria-hidden />
        </span>
        <p className="mt-3 text-sm font-semibold text-fg">Ask about your invoices</p>
        <p className="mx-auto mt-1 max-w-72 text-sm text-fg-muted">
          {empty
            ? "No invoices are indexed yet. Upload a few, then ask about vendors, totals and dates."
            : "Answers come from the stored invoices, with links to the ones used. Code does the maths."}
        </p>
      </div>
      {suggestions.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-9 rounded-xl" />
          <Skeleton className="h-9 rounded-xl" />
        </div>
      ) : (
        suggestions.data &&
        !empty && (
          <ul className="space-y-2" aria-label="Example questions">
            {suggestions.data.questions.map((question) => (
              <li key={question}>
                <button
                  type="button"
                  onClick={() => onPick(question)}
                  className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-left text-sm text-fg transition-colors hover:border-accent/40 hover:bg-accent-soft/40"
                >
                  {question}
                </button>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}

interface ChatPanelProps {
  chat: Chat;
  documentId: string | undefined;
  onClose: () => void;
}

/** The Ask AI panel (PRD 0010 D11): a card on wide screens, a full-screen sheet on phones. */
export function ChatPanel({ chat, documentId, onClose }: ChatPanelProps) {
  const titleId = useId();
  const narrow = useIsNarrow();
  const [draft, setDraft] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => input.current?.focus(), []);

  // Show the newest question at the top, so a long answer is read from its start.
  useEffect(() => {
    const element = scroller.current;
    const last = element?.querySelector<HTMLElement>("ol > li:last-child");
    if (element && last) element.scrollTop = Math.max(0, last.offsetTop - 12);
  }, [chat.entries]);

  useEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 128)}px`;
  }, [draft]);

  const submit = (question: string) => {
    if (!canAsk(question) || chat.pending) return;
    chat.ask(question);
    setDraft("");
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit(draft);
  };

  const onInputKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit(draft);
    }
  };

  const onPanelKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !narrow || !panel.current) return;
    // Full-screen sheet on phones is modal: keep focus inside it.
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = items[0];
    const last = items.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const closeOnNarrow = () => {
    if (narrow) onClose();
  };
  const length = draft.trim().length;
  const tooLong = length > QUESTION_MAX;

  return (
    <div
      ref={panel}
      role="dialog"
      aria-modal={narrow || undefined}
      aria-labelledby={titleId}
      onKeyDown={onPanelKey}
      className={cx(
        "fixed z-40 flex flex-col overflow-hidden bg-surface",
        "inset-0 sm:inset-auto sm:right-4 sm:bottom-4 sm:h-[min(640px,calc(100dvh-6rem))] sm:w-[400px] sm:rounded-2xl sm:border sm:border-border sm:shadow-2xl",
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent">
          <Sparkles className="size-4.5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="text-sm font-semibold text-fg">
            Ask AI
          </h2>
          <p className="truncate text-xs text-fg-subtle">From your stored invoices</p>
        </div>
        <button
          type="button"
          onClick={() => {
            chat.reset();
            input.current?.focus();
          }}
          disabled={chat.entries.length === 0 && !chat.pending}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg disabled:pointer-events-none disabled:opacity-40"
        >
          <MessageSquarePlus className="size-4" aria-hidden />
          New chat
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close Ask AI"
          className="grid size-8 place-items-center rounded-lg text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg"
        >
          <X className="size-4.5" aria-hidden />
        </button>
      </div>

      <div ref={scroller} className="relative flex flex-1 flex-col overflow-y-auto overscroll-contain px-4 py-4">
        {chat.restoring ? (
          <div className="space-y-3" aria-label="Loading the conversation">
            <Skeleton className="ml-auto h-9 w-2/3 rounded-2xl" />
            <Skeleton className="h-20 w-5/6 rounded-2xl" />
          </div>
        ) : chat.entries.length === 0 ? (
          <Suggestions documentId={documentId} onPick={submit} />
        ) : (
          <ol className="space-y-3" aria-live="polite" aria-relevant="additions">
            {chat.entries.map((entry) => (
              <li key={entry.key} className="space-y-2">
                <UserBubble text={entry.question} />
                {entry.state === "pending" && <ThinkingBubble />}
                {entry.state === "error" && (
                  <ErrorBubble error={entry.error} onRetry={() => chat.retry(entry.key)} />
                )}
                {entry.state === "done" && <AnswerCard turn={entry.turn} onNavigate={closeOnNarrow} />}
              </li>
            ))}
          </ol>
        )}
      </div>

      <form onSubmit={onSubmit} className="border-t border-border px-3 pt-2.5 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        {documentId && (
          <p className="mb-2 flex items-center gap-1.5 px-1 text-xs text-fg-subtle">
            <FileText className="size-3.5" aria-hidden />
            Questions can refer to “this invoice”.
          </p>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-border-strong bg-surface px-2 py-1.5 focus-within:ring-2 focus-within:ring-ring">
          <label htmlFor={`${titleId}-input`} className="sr-only">
            Your question
          </label>
          <textarea
            id={`${titleId}-input`}
            ref={input}
            rows={1}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onInputKey}
            placeholder="Ask about vendors, totals, dates…"
            aria-describedby={length >= COUNTER_FROM ? `${titleId}-count` : undefined}
            className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-sm text-fg outline-none placeholder:text-fg-subtle"
          />
          <button
            type="submit"
            aria-label="Send question"
            disabled={!canAsk(draft) || chat.pending}
            className="mb-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-fg transition-colors hover:bg-accent-hover disabled:opacity-40"
          >
            <ArrowUp className="size-4.5" aria-hidden />
          </button>
        </div>
        {length >= COUNTER_FROM && (
          <p
            id={`${titleId}-count`}
            className={cx("mt-1 px-1 text-right text-xs tabular-nums", tooLong ? "text-danger" : "text-fg-subtle")}
          >
            {length} / {QUESTION_MAX}
          </p>
        )}
      </form>
    </div>
  );
}

import { useCallback, useState, type ReactNode } from "react";

import { AnnounceContext } from "./announce.ts";

/** Provides `useAnnounce()` and renders the visually hidden polite live region. */
export function LiveRegion({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");

  const announce = useCallback((next: string) => {
    // Clear first so the same message is announced again.
    setMessage("");
    window.setTimeout(() => setMessage(next), 50);
  }, []);

  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="live-region">
        {message}
      </div>
    </AnnounceContext.Provider>
  );
}

import { createContext, useContext } from "react";

/** Sends a short message to the polite aria-live region in the layout (PRD D15). */
export type Announce = (message: string) => void;

export const AnnounceContext = createContext<Announce>(() => {});

export function useAnnounce(): Announce {
  return useContext(AnnounceContext);
}

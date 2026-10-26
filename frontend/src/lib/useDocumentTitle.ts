import { useEffect } from "react";

export const APP_NAME = "Document Intelligence";

/** Sets the browser tab title for the current page (PRD D18). */
export function useDocumentTitle(title: string | null): void {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
  }, [title]);
}

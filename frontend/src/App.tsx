import type { RouteObject } from "react-router";

import { AppLayout } from "./components/layout/AppLayout.tsx";
import DocumentDetailPage from "./features/detail/DocumentDetailPage.tsx";
import DocumentsPage from "./features/documents/DocumentsPage.tsx";
import UploadPage from "./features/upload/UploadPage.tsx";
import NotFoundPage from "./pages/NotFoundPage.tsx";

/** Route table (PRD D1); used by the browser router and by tests with a memory router. */
export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: <UploadPage /> },
      { path: "/documents", element: <DocumentsPage /> },
      { path: "/documents/:id", element: <DocumentDetailPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

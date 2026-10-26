import { FileQuestion } from "lucide-react";
import { Link } from "react-router";

import { buttonClasses } from "../components/ui/buttonClasses.ts";
import { EmptyState } from "../components/ui/EmptyState.tsx";
import { useDocumentTitle } from "../lib/useDocumentTitle.ts";

export default function NotFoundPage() {
  useDocumentTitle("Page not found");
  return (
    <div className="py-10">
      <EmptyState
        pageHeading
        icon={<FileQuestion className="size-6" aria-hidden />}
        title="Page not found"
        description="The page you're looking for doesn't exist."
        action={
          <Link to="/" className={buttonClasses("primary")}>
            Go to upload
          </Link>
        }
      />
    </div>
  );
}

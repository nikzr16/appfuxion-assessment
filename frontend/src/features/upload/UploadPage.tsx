import { ArrowRight, FileSearch, ScanText, ShieldCheck, Sparkles, Upload } from "lucide-react";
import { Link } from "react-router";

import { PageHeader } from "../../components/PageHeader.tsx";
import { Alert } from "../../components/ui/Alert.tsx";
import { Button } from "../../components/ui/Button.tsx";
import { buttonClasses } from "../../components/ui/buttonClasses.ts";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { useDocumentTitle } from "../../lib/useDocumentTitle.ts";
import { DropZone } from "./DropZone.tsx";
import { UploadQueue } from "./UploadQueue.tsx";
import { useUploadQueue } from "./useUploadQueue.ts";

const STEPS = [
  { Icon: ScanText, title: "Read", text: "Text is pulled from the PDF, or read from the image by a vision model." },
  { Icon: FileSearch, title: "Extract", text: "Vendor, dates, totals and line items become structured data." },
  { Icon: ShieldCheck, title: "Validate", text: "Code checks the maths, dates and currency, and converts the total." },
  { Icon: Sparkles, title: "Summarise", text: "A short summary that calls out every problem found." },
];

function uploadLabel(running: boolean, queued: number): string {
  if (running) return "Uploading…";
  if (queued === 0) return "Upload";
  return `Upload ${queued} file${queued === 1 ? "" : "s"}`;
}

export default function UploadPage() {
  useDocumentTitle("Upload");
  const { items, notice, running, config, add, upload, retry, remove, clear } = useUploadQueue();

  const queued = items.filter((item) => item.state === "queued").length;
  const uploaded = items.filter((item) => item.state === "uploaded").length;
  const failed = items.filter((item) => item.state === "rejected").length;

  return (
    <>
      <PageHeader
        title="Upload documents"
        description="Add invoices or receipts. Each one is read, extracted, validated and summarised by AI agents."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <DropZone config={config} disabled={running} onFiles={add} />

          {notice && (
            <Alert tone="warning" role="alert" title="Too many files">
              {notice}
            </Alert>
          )}

          {items.length > 0 && (
            <Card>
              <CardHeader
                title="Files"
                description={`${items.length} selected`}
                actions={
                  <Button variant="ghost" size="sm" disabled={running} onClick={clear}>
                    Clear all
                  </Button>
                }
              />
              <CardBody>
                <UploadQueue items={items} running={running} onRemove={remove} onRetry={retry} />
              </CardBody>
              <div className="flex flex-col-reverse gap-3 border-t border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <p className="text-sm text-fg-muted" aria-live="polite">
                  {failed > 0 && !running
                    ? `${failed} file${failed === 1 ? "" : "s"} can't be uploaded. Remove ${failed === 1 ? "it" : "them"} or try again.`
                    : "Processing starts as soon as a file is uploaded."}
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  {uploaded > 0 && failed > 0 && !running && (
                    <Link to="/documents" className={buttonClasses("secondary")}>
                      Go to documents
                      <ArrowRight className="size-4" aria-hidden />
                    </Link>
                  )}
                  <Button
                    onClick={upload}
                    loading={running}
                    disabled={queued === 0}
                    icon={<Upload className="size-4" aria-hidden />}
                  >
                    {uploadLabel(running, queued)}
                  </Button>
                </div>
              </div>
            </Card>
          )}
        </div>

        <Card className="h-fit">
          <CardHeader title="How it works" description="Usually done in under a minute." />
          <CardBody>
            <ol className="space-y-4">
              {STEPS.map(({ Icon, title, text }, index) => (
                <li key={title} className="flex gap-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-surface-2 text-accent">
                    <Icon className="size-4.5" aria-hidden />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-fg">
                      <span className="text-fg-subtle tabular-nums">{index + 1}.</span> {title}
                    </p>
                    <p className="text-sm text-fg-muted">{text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      </div>
    </>
  );
}

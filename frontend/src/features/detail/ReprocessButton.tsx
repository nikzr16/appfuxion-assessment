import { useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client.ts";
import { markProcessing, useReprocess } from "../../api/queries.ts";
import { ErrorAlert } from "../../components/ui/Alert.tsx";
import { Button } from "../../components/ui/Button.tsx";
import { Dialog } from "../../components/ui/Dialog.tsx";
import { useAnnounce } from "../../components/ui/announce.ts";

interface ReprocessButtonProps {
  documentId: string;
  disabled: boolean;
  onAlreadyProcessing: () => void;
}

/** Reprocess with a confirm step (PRD D11): it re-runs every step and uses OpenAI tokens. */
export function ReprocessButton({ documentId, disabled, onAlreadyProcessing }: ReprocessButtonProps) {
  const [open, setOpen] = useState(false);
  const reprocess = useReprocess(documentId);
  const queryClient = useQueryClient();
  const announce = useAnnounce();

  function close() {
    setOpen(false);
    reprocess.reset();
  }

  function confirm() {
    reprocess.mutate(undefined, {
      onSuccess: () => {
        close();
        announce("Reprocessing started.");
      },
      onError: (error) => {
        if (error instanceof ApiError && error.code === "already_processing") {
          markProcessing(queryClient, documentId);
          close();
          onAlreadyProcessing();
        }
      },
    });
  }

  return (
    <>
      <Button
        variant="secondary"
        disabled={disabled}
        title={disabled ? "The document is being processed" : undefined}
        onClick={() => setOpen(true)}
        icon={<RotateCw className="size-4" aria-hidden />}
      >
        Reprocess
      </Button>
      <Dialog
        open={open}
        onClose={close}
        title="Reprocess this document?"
        description="The text and data are extracted again, validated and summarised. The current result is replaced when the new run finishes. This uses OpenAI tokens."
        footer={
          <>
            <Button variant="secondary" onClick={close} disabled={reprocess.isPending}>
              Cancel
            </Button>
            <Button onClick={confirm} loading={reprocess.isPending} icon={<RotateCw className="size-4" aria-hidden />}>
              Reprocess
            </Button>
          </>
        }
      >
        {reprocess.isError && <ErrorAlert error={reprocess.error} />}
      </Dialog>
    </>
  );
}

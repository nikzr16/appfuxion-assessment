import { Copy, Database, MessageSquareText, Timer } from "lucide-react";

import type { RetrievalMetrics } from "../../api/types.ts";
import { Card, CardBody, CardHeader } from "../../components/ui/Card.tsx";
import { EMPTY, formatCost, formatDuration } from "../../lib/format.ts";
import { Stat } from "./GuardrailsSection.tsx";

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** The invoice index, vendor-history flags and Ask AI questions (feature 0010, PRD D13). */
export function RetrievalSection({ data }: { data: RetrievalMetrics }) {
  return (
    <Card aria-labelledby="metrics-retrieval">
      <CardHeader
        id="metrics-retrieval"
        icon={<Database className="size-4.5" aria-hidden />}
        title="Retrieval & Ask AI"
        description="Invoices in the search index, what the vendor-history checks found, and the questions asked."
      />
      <CardBody>
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            icon={<Database className="size-4" aria-hidden />}
            label="Indexed invoices"
            value={data.documents_indexed}
            hint={
              data.documents_not_embedded > 0
                ? `${data.documents_not_embedded} without an embedding`
                : "All searchable by meaning"
            }
          />
          <Stat
            icon={<Copy className="size-4" aria-hidden />}
            label="Vendor-history flags"
            value={data.duplicate_flags + data.outlier_flags}
            hint={`${plural(data.duplicate_flags, "duplicate")}, ${plural(data.outlier_flags, "unusual amount")}`}
          />
          <Stat
            icon={<MessageSquareText className="size-4" aria-hidden />}
            label="Questions asked"
            value={data.questions}
            hint={`${plural(data.conversations, "chat")} · ${data.questions_failed} failed · ${data.questions_unanswerable} off-topic`}
          />
          <Stat
            icon={<Timer className="size-4" aria-hidden />}
            label="Avg answer time"
            value={data.avg_question_ms === null ? EMPTY : formatDuration(data.avg_question_ms)}
            hint={`${formatCost(data.avg_cost_per_question)} per question`}
          />
        </dl>
      </CardBody>
    </Card>
  );
}

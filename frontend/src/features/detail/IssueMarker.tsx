import type { ValidationIssue } from "../../api/types.ts";
import { SEVERITY_STYLE } from "../../components/severity.tsx";
import { worstSeverity } from "../../lib/issues.ts";

/** Small severity icon next to a value that has validation issues; the messages are its tooltip. */
export function IssueMarker({ issues }: { issues: ValidationIssue[] }) {
  const worst = worstSeverity(issues);
  if (!worst) return null;
  const { Icon, text, label } = SEVERITY_STYLE[worst];
  const messages = issues.map((issue) => issue.message).join("\n");
  return (
    <span className={`inline-flex shrink-0 ${text}`} title={messages}>
      <Icon className="size-4" aria-hidden />
      <span className="sr-only">
        {label}: {messages}
      </span>
    </span>
  );
}

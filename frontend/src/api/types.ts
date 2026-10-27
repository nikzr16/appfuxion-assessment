/**
 * Types mirroring the backend DTOs (docs/reference/folder-structure.md, "Schemas").
 * Money, quantities, dates and timestamps stay strings: money is a decimal string and
 * must never go through floating point; dates are ISO `YYYY-MM-DD`.
 */

export type DocumentStatus = "processing" | "completed" | "failed";

export interface DocumentRead {
  document_id: string;
  filename: string;
  version: number;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentList {
  items: DocumentRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentUploadResponse {
  document_id: string;
  status: DocumentStatus;
}

export type ExtractionMethod = "pdf_parser" | "vision";

export interface DocumentTextResponse {
  document_id: string;
  raw_text: string;
  method: ExtractionMethod;
  page_count: number;
}

export type DocumentType = "invoice" | "receipt" | "unknown";

export interface LineItem {
  description: string | null;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
}

export interface InvoiceData {
  document_type: DocumentType;
  vendor: string | null;
  vendor_address: string | null;
  vendor_tax_id: string | null;
  customer_name: string | null;
  customer_address: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  payment_terms: string | null;
  currency: string | null;
  subtotal: string | null;
  tax: string | null;
  total_amount: string | null;
  line_items: LineItem[];
}

export interface ExtractionResponse {
  document_id: string;
  structured_data: InvoiceData;
  model: string;
  prompt_version: string;
  attempts: number;
}

export type Severity = "error" | "warning" | "info";
export type ValidationStatus = "pass" | "warn" | "fail";

export interface ValidationIssue {
  field: string;
  code: string;
  severity: Severity;
  message: string;
  expected: string | null;
  actual: string | null;
}

export interface ValidationReport {
  status: ValidationStatus;
  issues: ValidationIssue[];
}

export interface ConversionResult {
  original_amount: string;
  from_currency: string;
  to_currency: string;
  rate: string;
  converted_amount: string;
  rate_date: string;
  source: string;
}

export interface AgentResult {
  document_id: string;
  structured_data: InvoiceData;
  validation: ValidationReport;
  conversion: ConversionResult | null;
  summary: string;
  /** Feature 0008; `null` for unknown documents, absent/`null` for results saved before 0008. */
  confidence?: ConfidenceReport | null;
}

// -- Guardrails (feature 0008) -------------------------------------------------------

export type GroundingStatus = "grounded" | "weak" | "ungrounded" | "inferred" | "skipped";
export type ConfidenceLabel = "high" | "medium" | "low";

export interface FieldConfidence {
  path: string;
  score: number;
  label: ConfidenceLabel;
  grounding: GroundingStatus;
  page: number | null;
  /** Character offsets into `raw_text` as `GET /text` returns it. */
  start: number | null;
  end: number | null;
  reasons: string[];
}

export interface ConfidenceReport {
  overall: number;
  label: ConfidenceLabel;
  needs_review: boolean;
  review_fields: string[];
  components: { fields: number; completeness: number; validation: number };
  fields: Record<string, FieldConfidence>;
}

export type AgentMode = "single" | "multi";
export type RunTrigger = "upload" | "reprocess";
export type RunStatus = "running" | "completed" | "failed";
export type StepStatus = "ok" | "error";

export interface ToolStep {
  index: number;
  turn: number;
  tool: string;
  arguments: Record<string, unknown>;
  status: StepStatus;
  result: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
  duration_ms: number;
  started_at: string;
}

export interface AgentRunRead {
  id: string;
  document_id: string;
  mode: AgentMode;
  trigger: RunTrigger;
  status: RunStatus;
  steps: ToolStep[];
  summary: string | null;
  error_code: string | null;
  error: string | null;
  model: string | null;
  agent_prompt_version: string;
  summary_prompt_version: string;
  prompt_tokens: number;
  completion_tokens: number;
  started_at: string;
  finished_at: string | null;
}

export interface ClientConfig {
  max_upload_mb: number;
  accepted_content_types: string[];
  base_currency: string;
}

// -- Observability (0007) ------------------------------------------------------------
// Estimated costs are USD decimal strings (6 places) or `null` for an unpriced model.

export type LLMCallStatus = "ok" | "error";

export interface UsageTotals {
  llm_calls: number;
  failed_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: string | null;
  /** False when some calls used a model missing from the price table. */
  cost_complete: boolean;
}

export interface GroupTotals extends UsageTotals {
  key: string;
  avg_latency_ms: number;
}

export interface TraceRun {
  run_id: string;
  mode: AgentMode;
  trigger: RunTrigger;
  status: RunStatus;
  error_code: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  queue_ms: number | null;
  processing_ms: number | null;
  run_prompt_tokens: number;
  run_completion_tokens: number;
}

export interface ToolSpan {
  kind: "tool";
  step_index: number;
  turn: number;
  tool: string;
  status: StepStatus;
  error_code: string | null;
  started_at: string;
  offset_ms: number;
  duration_ms: number;
}

export interface LLMSpan {
  kind: "llm";
  id: string;
  /** The tool step the call was made in; `null` for the agent's own turns. */
  step_index: number | null;
  purpose: string;
  agent: string | null;
  model: string;
  prompt_version: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: string | null;
  status: LLMCallStatus;
  error_code: string | null;
  started_at: string;
  offset_ms: number;
  duration_ms: number;
  /** 1 = first try; 2+ = a transient-error retry (feature 0008). */
  attempt?: number;
}

export type TraceSpan = ToolSpan | LLMSpan;

export interface DocumentTrace {
  document_id: string;
  uploaded_at: string;
  run: TraceRun | null;
  llm_calls_recorded: boolean;
  totals: UsageTotals;
  by_purpose: GroupTotals[];
  by_agent: GroupTotals[];
  spans: TraceSpan[];
  prices_as_of: string;
}

export interface RunStats {
  total: number;
  running: number;
  completed: number;
  failed: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface DocumentMetrics {
  total: number;
  processing: number;
  completed: number;
  failed: number;
  success_rate: number | null;
}

export interface LLMMetrics extends UsageTotals {
  error_rate: number | null;
  documents_with_usage: number;
  avg_tokens_per_document: number | null;
  avg_cost_per_document: string | null;
}

export interface MetricsSummary {
  window_days: number | null;
  since: string | null;
  generated_at: string;
  ledger_since: string | null;
  documents: DocumentMetrics;
  runs: RunStats;
  llm: LLMMetrics;
  by_model: GroupTotals[];
  by_purpose: GroupTotals[];
  /** Feature 0008. */
  guardrails?: GuardrailMetrics;
  prices_as_of: string;
}

export interface GuardrailMetrics {
  runs_scored: number;
  avg_confidence: number | null;
  by_label: Record<ConfidenceLabel, number>;
  needs_review: number;
  needs_review_rate: number | null;
  values_checked: number;
  values_grounded: number;
  grounding_rate: number | null;
  grounding_retry_extractions: number;
  transient_retries: number;
}

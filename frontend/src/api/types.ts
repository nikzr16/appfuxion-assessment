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

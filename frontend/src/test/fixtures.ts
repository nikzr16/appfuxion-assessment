import type {
  AgentResult,
  AgentRunRead,
  DocumentRead,
  InvoiceData,
  ToolStep,
  ValidationIssue,
} from "../api/types.ts";

export const DOC_ID = "3721d29d-87a3-4f38-9c4c-7f50e16fb346";

export function makeDocument(overrides: Partial<DocumentRead> = {}): DocumentRead {
  return {
    document_id: DOC_ID,
    filename: "invoice.pdf",
    version: 1,
    content_type: "application/pdf",
    size_bytes: 2048,
    status: "completed",
    error: null,
    created_at: "2026-10-27T01:02:00+08:00",
    updated_at: "2026-10-27T01:02:30+08:00",
    ...overrides,
  };
}

export function makeInvoice(overrides: Partial<InvoiceData> = {}): InvoiceData {
  return {
    document_type: "invoice",
    vendor: "Brightlane Logistics Sdn Bhd",
    vendor_address: "12 Jalan Teknologi, Petaling Jaya",
    vendor_tax_id: "W10-1808-32000123",
    customer_name: "Mesiniaga Berhad",
    customer_address: null,
    invoice_number: "BL-88731",
    invoice_date: "2026-10-02",
    due_date: "2026-09-01",
    payment_terms: "Net 30",
    currency: "MYR",
    subtotal: "1095.00",
    tax: "87.60",
    total_amount: "1182.60",
    line_items: [
      { description: "Express delivery", quantity: "3", unit_price: "180.00", amount: "540.00" },
      { description: "Pallet storage", quantity: "6", unit_price: "75.00", amount: "480.00" },
      { description: "Insurance", quantity: "1", unit_price: "65.00", amount: "65.00" },
    ],
    ...overrides,
  };
}

export function makeIssue(overrides: Partial<ValidationIssue> = {}): ValidationIssue {
  return {
    field: "due_date",
    code: "due_before_invoice",
    severity: "error",
    message: "The due date 2026-09-01 is before the invoice date 2026-10-02.",
    expected: null,
    actual: null,
    ...overrides,
  };
}

export function makeResult(overrides: Partial<AgentResult> = {}): AgentResult {
  return {
    document_id: DOC_ID,
    structured_data: makeInvoice(),
    validation: {
      status: "fail",
      issues: [
        makeIssue(),
        makeIssue({
          field: "line_items[1].amount",
          code: "line_amount_mismatch",
          severity: "warning",
          message: "Line 2: quantity 6 x unit price 75.00 = 450.00 MYR, but the line amount is 480.00 MYR.",
          expected: "450.00",
          actual: "480.00",
        }),
      ],
    },
    conversion: null,
    summary: "This is an invoice from Brightlane Logistics with a due date before its invoice date.",
    ...overrides,
  };
}

export function makeStep(overrides: Partial<ToolStep> = {}): ToolStep {
  return {
    index: 0,
    turn: 1,
    tool: "extract_text",
    arguments: {},
    status: "ok",
    result: {},
    error: null,
    duration_ms: 44,
    started_at: "2026-10-27T01:02:01+08:00",
    ...overrides,
  };
}

export const ALL_STEPS: ToolStep[] = [
  makeStep({ index: 0, tool: "extract_text", duration_ms: 44 }),
  makeStep({ index: 1, tool: "extract_structured_data", duration_ms: 2800 }),
  makeStep({ index: 2, tool: "validate_invoice", duration_ms: 1 }),
  makeStep({ index: 3, tool: "generate_summary", duration_ms: 1700 }),
];

export function makeRun(overrides: Partial<AgentRunRead> = {}): AgentRunRead {
  return {
    id: "run-1",
    document_id: DOC_ID,
    mode: "single",
    trigger: "upload",
    status: "completed",
    steps: ALL_STEPS,
    summary: "summary",
    error_code: null,
    error: null,
    model: "gpt-4.1-mini",
    agent_prompt_version: "agent.document.v1",
    summary_prompt_version: "agent.summary.v1",
    prompt_tokens: 1200,
    completion_tokens: 300,
    started_at: "2026-10-27T01:02:00+08:00",
    finished_at: "2026-10-27T01:02:12+08:00",
    ...overrides,
  };
}

export const CONFIG = {
  max_upload_mb: 10,
  accepted_content_types: ["application/pdf", "image/jpeg", "image/png"],
  base_currency: "MYR",
};

export function pdfFile(name = "invoice.pdf", size = 2048): File {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

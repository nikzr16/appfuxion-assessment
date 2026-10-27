import type {
  AgentPart,
  AgentResult,
  AgentRunRead,
  ConfidenceReport,
  DocumentRead,
  DocumentTrace,
  FieldConfidence,
  InvoiceData,
  LLMSpan,
  LayoutResponse,
  ToolSpan,
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

/** A completed multi-agent run (feature 0011): each step names its agent. */
export const MULTI_STEPS: ToolStep[] = [
  makeStep({ index: 0, turn: 1, agent: "extraction", tool: "extract_text", duration_ms: 44 }),
  makeStep({ index: 1, turn: 2, agent: "extraction", tool: "extract_structured_data", duration_ms: 2800 }),
  makeStep({ index: 2, turn: 3, agent: "validation", tool: "validate_invoice", duration_ms: 1 }),
  makeStep({ index: 3, turn: 4, agent: "reporting", tool: "generate_summary", duration_ms: 1700 }),
];

export function makeAgentPart(overrides: Partial<AgentPart> = {}): AgentPart {
  return {
    agent: "extraction",
    status: "completed",
    prompt_version: "agent.extraction.v1",
    turns: 2,
    steps: 2,
    prompt_tokens: 600,
    completion_tokens: 150,
    started_at: "2026-10-27T01:02:00+08:00",
    finished_at: "2026-10-27T01:02:05+08:00",
    error_code: null,
    ...overrides,
  };
}

export function makeMultiRun(overrides: Partial<AgentRunRead> = {}): AgentRunRead {
  return makeRun({
    mode: "multi",
    agent_prompt_version: "agent.multi.v1",
    steps: MULTI_STEPS,
    agents: [
      makeAgentPart(),
      makeAgentPart({ agent: "validation", prompt_version: "agent.validation.v1", turns: 1, steps: 1 }),
      makeAgentPart({ agent: "reporting", prompt_version: "agent.reporting.v1", turns: 1, steps: 1 }),
    ],
    ...overrides,
  });
}

export const CONFIG = {
  max_upload_mb: 10,
  accepted_content_types: ["application/pdf", "image/jpeg", "image/png"],
  base_currency: "MYR",
};

export function pdfFile(name = "invoice.pdf", size = 2048): File {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

/** A completed run's trace (`GET /trace`) matching `makeRun()` and `ALL_STEPS`. */
export function makeTrace(overrides: Partial<DocumentTrace> = {}): DocumentTrace {
  const at = (ms: number) => new Date(Date.parse("2026-10-27T01:02:00+08:00") + ms).toISOString();
  const llm = (
    id: string,
    purpose: string,
    stepIndex: number | null,
    offset: number,
    duration: number,
    extra: Partial<LLMSpan> = {},
  ): LLMSpan => ({
    kind: "llm",
    id,
    step_index: stepIndex,
    purpose,
    agent: "document",
    model: "gpt-4.1-mini-2025-04-14",
    prompt_version: `${purpose}.v1`,
    prompt_tokens: 300,
    completion_tokens: 75,
    total_tokens: 375,
    cost_usd: "0.000240",
    status: "ok",
    error_code: null,
    started_at: at(offset),
    offset_ms: offset,
    duration_ms: duration,
    ...extra,
  });
  const tool = (step: ToolStep, offset: number): ToolSpan => ({
    kind: "tool",
    step_index: step.index,
    turn: step.turn,
    tool: step.tool,
    status: step.status,
    error_code: step.error?.code ?? null,
    started_at: at(offset),
    offset_ms: offset,
    duration_ms: step.duration_ms,
  });
  const [text, structured, validate, summary] = ALL_STEPS as [ToolStep, ToolStep, ToolStep, ToolStep];
  return {
    document_id: DOC_ID,
    uploaded_at: "2026-10-27T01:01:59+08:00",
    run: {
      run_id: "run-1",
      mode: "single",
      trigger: "upload",
      status: "completed",
      error_code: null,
      error: null,
      started_at: "2026-10-27T01:02:00+08:00",
      finished_at: "2026-10-27T01:02:12+08:00",
      queue_ms: 850,
      processing_ms: 12_000,
      run_prompt_tokens: 1200,
      run_completion_tokens: 300,
    },
    llm_calls_recorded: true,
    totals: {
      llm_calls: 6,
      failed_calls: 0,
      prompt_tokens: 1800,
      completion_tokens: 450,
      total_tokens: 2250,
      cost_usd: "0.001440",
      cost_complete: true,
    },
    by_purpose: [
      { key: "agent_loop", llm_calls: 4, failed_calls: 0, prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500, cost_usd: "0.000960", cost_complete: true, avg_latency_ms: 900 },
      { key: "structured_extraction", llm_calls: 1, failed_calls: 0, prompt_tokens: 300, completion_tokens: 75, total_tokens: 375, cost_usd: "0.000240", cost_complete: true, avg_latency_ms: 2700 },
      { key: "summary", llm_calls: 1, failed_calls: 0, prompt_tokens: 300, completion_tokens: 75, total_tokens: 375, cost_usd: "0.000240", cost_complete: true, avg_latency_ms: 1600 },
    ],
    by_agent: [
      { key: "document", llm_calls: 6, failed_calls: 0, prompt_tokens: 1800, completion_tokens: 450, total_tokens: 2250, cost_usd: "0.001440", cost_complete: true, avg_latency_ms: 1150 },
    ],
    spans: [
      llm("c1", "agent_loop", null, 10, 900),
      tool(text, 920),
      llm("c2", "agent_loop", null, 970, 800),
      tool(structured, 1780),
      llm("c3", "structured_extraction", 1, 1790, 2700),
      llm("c4", "agent_loop", null, 4600, 950),
      tool(validate, 5560),
      llm("c5", "agent_loop", null, 5570, 950),
      tool(summary, 6530),
      llm("c6", "summary", 3, 6540, 1600),
    ],
    prices_as_of: "2026-10-27",
    ...overrides,
  };
}

/** A confidence report for `makeResult()`: the vendor is not in the text, everything else is. */
export function makeConfidence(overrides: Partial<ConfidenceReport> = {}): ConfidenceReport {
  const field = (path: string, overrides: Partial<FieldConfidence> = {}): FieldConfidence => ({
    path,
    score: 1,
    label: "high",
    grounding: "grounded",
    page: 1,
    start: 8,
    end: 16,
    reasons: ["Found in the document text on page 1"],
    ...overrides,
  });
  return {
    overall: 0.55,
    label: "low",
    needs_review: true,
    review_fields: ["vendor"],
    components: { fields: 0.8, completeness: 1, validation: 0.3 },
    fields: {
      vendor: field("vendor", {
        score: 0.2,
        label: "low",
        grounding: "ungrounded",
        page: null,
        start: null,
        end: null,
        reasons: ["Not found in the document text"],
      }),
      invoice_number: field("invoice_number"),
      currency: field("currency", {
        score: 0.9,
        label: "high",
        grounding: "inferred",
        reasons: ["Inferred from the printed symbol 'RM' on page 1"],
      }),
      "line_items[0].amount": field("line_items[0].amount", { start: 0, end: 7 }),
    },
    ...overrides,
  };
}

/** A text-PDF layout (feature 0009): one line-item table and four blocks on one page. */
export function makeLayout(overrides: Partial<LayoutResponse> = {}): LayoutResponse {
  const row = (cells: string[], top: number): LayoutResponse["tables"][number]["rows"][number] => ({
    page: 1,
    cells,
    box: [0.08, top, 0.92, top + 0.03],
    cell_boxes: null,
  });
  return {
    document_id: DOC_ID,
    layout_id: "6b0d4c8e-2f4a-4a43-9f25-7c1f0a5a1c11",
    source: "pdf_parser",
    layout_version: "layout.v1",
    run_id: null,
    created_at: "2026-10-27T10:00:00Z",
    page_count: 1,
    pages: [{ page: 1, width: 595, height: 842 }],
    tables: [
      {
        index: 0,
        pages: [1],
        box: [0.08, 0.3, 0.92, 0.42],
        strategy: "lines",
        header: ["Description", "Qty", "Unit Price", "Amount"],
        columns: ["description", "quantity", "unit_price", "amount"],
        kind: "line_items",
        rows: [
          row(["Express delivery", "3", "180.00", "540.00"], 0.33),
          row(["Pallet storage", "6", "75.00", "480.00"], 0.36),
          row(["Insurance", "1", "65.00", "65.00"], 0.39),
        ],
      },
    ],
    blocks: [
      { type: "header", page: 1, order: 0, text: "Brightlane Logistics", box: [0.08, 0.05, 0.4, 0.1] },
      { type: "document_info", page: 1, order: 1, text: "Invoice No: BL-88731", box: [0.6, 0.05, 0.9, 0.1] },
      { type: "line_items", page: 1, order: 2, text: "Description | Qty", box: [0.08, 0.3, 0.92, 0.42] },
      { type: "totals", page: 1, order: 3, text: "Total RM 1,182.60", box: [0.6, 0.45, 0.92, 0.5] },
    ],
    history: [],
    ...overrides,
  };
}

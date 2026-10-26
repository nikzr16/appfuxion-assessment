"""Fixtures for the agent tests: scripted tool-call turns, sample data and real documents."""

import itertools
import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.llm import FakeLLM, LLMResponse, TokenUsage, ToolCall
from app.core.storage import LocalStorage
from app.modules.agent import service as agent_service
from app.modules.documents import service as documents_service
from app.modules.documents.pipeline import register_pipeline_runner
from app.modules.documents.schema import UploadedFile
from app.modules.structured_extraction.schema import InvoiceData
from tests.modules.text_extraction import samples

TURN_USAGE = TokenUsage(prompt_tokens=10, completion_tokens=5)
SUMMARY = (
    "Invoice INV-2025-001 from ACME Supplies Sdn Bhd, dated 2025-03-04, totals 123.45 MYR "
    "and passed validation."
)
MakeDocument = Callable[..., uuid.UUID]

_call_ids = itertools.count(1)


def tool_turn(*calls: str | tuple[str, dict[str, Any]]) -> LLMResponse:
    """A model turn that requests the given tool calls (``name`` or ``(name, arguments)``)."""
    tool_calls = []
    for call in calls:
        name, arguments = (call, {}) if isinstance(call, str) else call
        tool_calls.append(
            ToolCall(id=f"call_{next(_call_ids)}", name=name, arguments=json.dumps(arguments))
        )
    return LLMResponse(
        content=None, usage=TURN_USAGE, model="fake-model", tool_calls=tuple(tool_calls)
    )


def text_turn(text: str) -> LLMResponse:
    """A model turn with no tool call."""
    return LLMResponse(content=text, usage=TURN_USAGE, model="fake-model")


def invoice(**overrides: Any) -> InvoiceData:
    """A complete, consistent invoice (validation passes with one ``info`` note)."""
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "ACME Supplies Sdn Bhd",
        "vendor_address": None,
        "vendor_tax_id": None,
        "customer_name": None,
        "customer_address": None,
        "invoice_number": "INV-2025-001",
        "invoice_date": "2025-03-04",
        "due_date": None,
        "payment_terms": None,
        "currency": "MYR",
        "subtotal": None,
        "tax": None,
        "total_amount": "123.45",
        "line_items": [
            {"description": "Widget", "quantity": "2", "unit_price": "10.00", "amount": "20.00"},
            {"description": "Gadget", "quantity": "1", "unit_price": "103.45", "amount": "103.45"},
        ],
    }
    data.update(overrides)
    return InvoiceData.model_validate(data)


def unknown_document() -> InvoiceData:
    fields = dict.fromkeys(invoice().model_dump(), None)
    return InvoiceData.model_validate({**fields, "document_type": "unknown", "line_items": []})


def happy_script(data: InvoiceData | None = None, summary: str = SUMMARY) -> list[Any]:
    """Agent turns plus the structured-extraction and summary replies, in call order."""
    return [
        tool_turn("extract_text"),
        tool_turn("extract_structured_data"),
        data or invoice(),
        tool_turn("validate_invoice"),
        tool_turn("generate_summary"),
        summary,
    ]


@pytest.fixture(autouse=True)
def agent_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the agent settings so a developer's ``.env`` cannot change the tests."""
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_mode", "single")
    monkeypatch.setattr(settings, "base_currency", "MYR")
    monkeypatch.setattr(settings, "agent_max_steps", 8)


@pytest.fixture
def agent_pipeline() -> Iterator[None]:
    """Uploads run the real Document Agent (the global default is a no-op)."""
    register_pipeline_runner(agent_service.run_document_agent)
    yield
    register_pipeline_runner(None)


@pytest.fixture
def make_document(db_session: Session, storage: LocalStorage) -> MakeDocument:
    """A stored ``processing`` document; by default a text-layer PDF (no vision call)."""

    def make(data: bytes | None = None, content_type: str = "application/pdf") -> uuid.UUID:
        upload = UploadedFile(
            filename="invoice.pdf" if content_type == "application/pdf" else "invoice.png",
            content_type=content_type,
            data=data if data is not None else samples.text_pdf(),
        )
        return documents_service.create_document(db_session, storage, upload).document_id

    return make


@pytest.fixture
def run_agent(storage: LocalStorage) -> Callable[..., None]:
    """Run the Document Agent synchronously on a scripted ``FakeLLM``."""

    def run(document_id: uuid.UUID, llm: FakeLLM, **kwargs: Any) -> None:
        agent_service.run_document_agent(document_id, llm=llm, storage=storage, **kwargs)

    return run

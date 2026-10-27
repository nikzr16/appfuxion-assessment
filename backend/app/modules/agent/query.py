"""The Query Agent (PRD 0010 D8): answers questions about the stored invoices.

One turn = one ``POST /query``: the agent sees the conversation's last ``MEMORY_TURNS``
answers, may call ``search_invoices`` / ``get_vendor_history`` (code does every sum and
comparison) and ends with ``submit_answer``. Code then keeps only citations the tools
returned and checks every number in the answer against the tool results.
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, LLMError, NotFoundError
from app.core.llm import Agent, LLMClient, Message, TokenUsage
from app.core.logging import bind_trace
from app.modules.agent import crud, prompts
from app.modules.agent.model import QueryRun
from app.modules.agent.runner import AgentRunError, AgentRunner, Tool, ToolError
from app.modules.agent.schema import (
    Citation,
    ConversationRead,
    QueryRequest,
    QueryResponse,
    QuerySuggestions,
    QueryTurn,
    QueryUsage,
    RunStatus,
    ToolStep,
)
from app.modules.documents import service as documents_service
from app.modules.retrieval import service as retrieval_service
from app.modules.retrieval.schema import (
    IndexEntry,
    NotIndexedError,
    SearchFilters,
    VendorNotFoundError,
)

logger = logging.getLogger(__name__)

# Earlier completed turns the agent sees (PRD D8).
MEMORY_TURNS = 10
# Invoices listed in one tool result (the statistics cover all of them).
TOOL_INVOICES = 20
# User-supplied text (vendor names, filenames) is cut to this length in tool results.
MAX_FIELD_CHARS = 120

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class QueryFailedError(AppError):
    status_code = 502
    code = "query_failed"


@dataclass
class _Answer:
    text: str
    cited: list[str]
    answerable: bool
    verified: bool


@dataclass
class QueryToolContext:
    db: Session
    llm: LLMClient
    base_currency: str
    seen_ids: set[str] = field(default_factory=set)
    known_numbers: set[str] = field(default_factory=set)
    answer: _Answer | None = None
    numbers_retry_used: bool = False
    embedding_tokens: int = 0

    def remember(self, payload: Any) -> None:
        """Document IDs and numbers the model may use from now on."""
        text = json.dumps(payload, default=str)
        self.seen_ids.update(_UUID.findall(text))
        self.known_numbers.update(retrieval_service.number_tokens(text))


# -- Tools ----------------------------------------------------------------------------------


def _nullable(kind: str, description: str, **extra: Any) -> dict[str, Any]:
    return {"type": [kind, "null"], "description": description, **extra}


_SEARCH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": _nullable("string", "Free text, an invoice number or a filename."),
        "vendor": _nullable("string", "Vendor name or tax ID."),
        "invoice_number": _nullable("string", "Invoice number (prefix match)."),
        "date_from": _nullable("string", "Earliest invoice date, YYYY-MM-DD."),
        "date_to": _nullable("string", "Latest invoice date, YYYY-MM-DD."),
        "currency": _nullable("string", "ISO 4217 code of the invoice currency."),
        "min_total": _nullable("number", "Smallest total in the base currency."),
        "max_total": _nullable("number", "Largest total in the base currency."),
        "document_type": _nullable(
            "string", "invoice or receipt.", enum=["invoice", "receipt", None]
        ),
        "limit": _nullable("integer", "How many invoices to list (1-20, default 5)."),
    },
    "required": [
        "text",
        "vendor",
        "invoice_number",
        "date_from",
        "date_to",
        "currency",
        "min_total",
        "max_total",
        "document_type",
        "limit",
    ],
    "additionalProperties": False,
}

_HISTORY_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_id": _nullable("string", "A document ID (UUID) to compare."),
        "invoice_number": _nullable("string", "An invoice number to compare."),
        "vendor": _nullable("string", "A vendor name or tax ID."),
        "date_from": _nullable("string", "Earliest invoice date, YYYY-MM-DD."),
        "date_to": _nullable("string", "Latest invoice date, YYYY-MM-DD."),
    },
    "required": ["document_id", "invoice_number", "vendor", "date_from", "date_to"],
    "additionalProperties": False,
}

_ANSWER_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "The answer in plain text."},
        "cited_document_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "document_id of every invoice the answer relies on.",
        },
        "answerable": {
            "type": "boolean",
            "description": "false when the question is not about the stored invoices.",
        },
    },
    "required": ["answer", "cited_document_ids", "answerable"],
    "additionalProperties": False,
}


def build_query_tools(ctx: QueryToolContext) -> list[Tool]:
    return [
        Tool(
            name="search_invoices",
            description=(
                "Find stored invoices by filters and/or free text. Returns the matching "
                "invoices (newest first, or most similar first for text), how many match, "
                "and code-computed totals (sum, min, max, median, average) in the base "
                "currency."
            ),
            parameters=_SEARCH_PARAMETERS,
            handler=lambda args: _search_invoices(ctx, args),
        ),
        Tool(
            name="get_vendor_history",
            description=(
                "One vendor's invoices with code-computed statistics in the base currency. "
                "Give a document_id or an invoice_number to also get where that invoice "
                "sits (difference from the median, rank, below / within / above the usual "
                "range); or give a vendor name."
            ),
            parameters=_HISTORY_PARAMETERS,
            handler=lambda args: _get_vendor_history(ctx, args),
        ),
        Tool(
            name="submit_answer",
            description="Give the final answer. Call it exactly once, last.",
            parameters=_ANSWER_PARAMETERS,
            handler=lambda args: _submit_answer(ctx, args),
        ),
    ]


def _short(value: str | None) -> str | None:
    if value is None:
        return None
    return value if len(value) <= MAX_FIELD_CHARS else value[: MAX_FIELD_CHARS - 1] + "…"


def _invoice(entry: IndexEntry, similarity: float | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "document_id": str(entry.document_id),
        "filename": _short(entry.filename),
        "vendor": _short(entry.vendor),
        "invoice_number": _short(entry.invoice_number),
        "invoice_date": entry.invoice_date.isoformat() if entry.invoice_date else None,
        "total_amount": _money(entry.total_amount),
        "currency": entry.currency,
        "total_in_base_currency": _money(entry.total_base),
        "needs_review": entry.needs_review,
    }
    if similarity is not None:
        item["similarity"] = similarity
    return item


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _date(arguments: dict[str, Any], name: str) -> date | None:
    value = arguments.get(name)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ToolError("invalid_arguments", f"{name} must be a date like 2026-01-31.") from exc


def _search_invoices(ctx: QueryToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    values = {k: v for k, v in arguments.items() if v not in (None, "")}
    for name in ("min_total", "max_total"):
        if name in values:
            values[name] = Decimal(str(values[name]))
    try:
        filters = SearchFilters.model_validate(values)
    except ValidationError as exc:
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
        raise ToolError("invalid_arguments", f"Invalid search arguments: {fields}.") from exc
    result = retrieval_service.search(ctx.db, ctx.llm, filters)
    ctx.embedding_tokens += result.embedding_tokens
    payload: dict[str, Any] = {
        "total_matches": result.total_matches,
        "invoices": [_invoice(hit, hit.similarity) for hit in result.items],
        "totals": result.aggregates.model_dump(mode="json") if result.aggregates else None,
    }
    if result.vendor_candidates:
        payload["no_vendor_match"] = {"similar_vendor_names": result.vendor_candidates}
    if result.note:
        payload["note"] = result.note
    ctx.remember(payload)
    return payload


def _get_vendor_history(ctx: QueryToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    raw_id = arguments.get("document_id")
    number = arguments.get("invoice_number") or None
    vendor = arguments.get("vendor") or None
    document_id = None
    if raw_id:
        try:
            document_id = uuid.UUID(str(raw_id))
        except ValueError as exc:
            raise ToolError("invalid_arguments", "document_id must be a UUID.") from exc
    if document_id is None and number is None and vendor is None:
        raise ToolError("invalid_arguments", "Give a document_id, an invoice_number or a vendor.")
    try:
        history = retrieval_service.vendor_history(
            ctx.db,
            document_id=document_id,
            invoice_number=number,
            vendor=vendor,
            date_from=_date(arguments, "date_from"),
            date_to=_date(arguments, "date_to"),
        )
    except (VendorNotFoundError, NotIndexedError, NotFoundError) as exc:
        raise ToolError(exc.code, exc.message) from exc
    target = history.target
    payload: dict[str, Any] = {
        "vendor": _short(history.vendor),
        "matched_by": history.match_rule.value if history.match_rule else None,
        "base_currency": history.base_currency,
        "statistics_of_other_invoices": history.stats.model_dump(mode="json"),
        "invoices": [_invoice(entry) for entry in history.invoices[:TOOL_INVOICES]],
    }
    if target is not None:
        payload["target"] = target.model_dump(mode="json") | {
            "earlier_invoices": history.earlier,
            "later_invoices": history.later,
            "same_invoice_number": [str(d.document_id) for d in history.duplicates],
        }
    ctx.remember(payload)
    return payload


def _submit_answer(ctx: QueryToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("answerable") is False:
        ctx.answer = _Answer(prompts.QUERY_REFUSAL, [], answerable=False, verified=True)
        return {"accepted": True}
    text = " ".join(str(arguments.get("answer") or "").split())
    if not text:
        raise ToolError("invalid_arguments", "The answer is empty.")
    cited: list[str] = []
    for raw in arguments.get("cited_document_ids") or []:
        value = str(raw).strip().lower()
        if value in ctx.seen_ids and value not in cited:
            cited.append(value)
    missing = retrieval_service.unverified_numbers(text, ctx.known_numbers)
    if missing and not ctx.numbers_retry_used:
        ctx.numbers_retry_used = True
        raise ToolError(
            "numbers_not_found", prompts.NUMBERS_RETRY.format(numbers=", ".join(missing))
        )
    ctx.answer = _Answer(text, cited, answerable=True, verified=not missing)
    return {"accepted": True, "numbers_verified": not missing, "citations": len(cited)}


# -- One turn ---------------------------------------------------------------------------------


def ask(
    db: Session, llm: LLMClient, request: QueryRequest, *, today: date | None = None
) -> QueryResponse:
    settings = get_settings()
    context_entry: IndexEntry | None = None
    if request.document_id is not None:
        documents_service.get_document(db, request.document_id)  # 404 for an unknown id
        context_entry = retrieval_service.get_entry(db, request.document_id)

    if request.conversation_id is not None:
        conversation = crud.lock_conversation(db, request.conversation_id)
        if conversation is None:
            raise NotFoundError(f"Conversation not found: {request.conversation_id}")
    else:
        conversation = crud.create_conversation(db)
    memory = crud.recent_completed_turns(db, conversation.id, limit=MEMORY_TURNS)
    run = crud.create_query_run(
        db,
        conversation_id=conversation.id,
        turn=crud.next_turn(db, conversation.id),
        question=request.question,
        document_id=request.document_id,
        model=settings.openai_model,
        prompt_version=prompts.QUERY_PROMPT_VERSION,
    )
    crud.touch_conversation(db, conversation.id)
    db.commit()

    ctx = QueryToolContext(db=db, llm=llm, base_currency=settings.base_currency)
    for earlier in memory:
        ctx.remember([step.get("result") for step in earlier.steps])
    ctx.known_numbers.update(retrieval_service.number_tokens(request.question))
    messages = _messages(request, memory, context_entry, ctx, settings.base_currency, today)
    runner = AgentRunner(
        llm,
        build_query_tools(ctx),
        max_steps=settings.query_max_steps,
        tool_choice="required",
        prompt_version=prompts.QUERY_PROMPT_VERSION,
    )
    started = time.perf_counter()
    with bind_trace(agent=Agent.QUERY, query_run_id=str(run.id)):
        logger.info("query started", extra={"conversation_id": str(conversation.id)})
        try:
            outcome = runner.run(messages, done=lambda: ctx.answer is not None)
        except AgentRunError as exc:
            db.rollback()
            crud.finish_query_run(
                db, run.id, values=_failed_values(exc.code, exc.message, exc, ctx)
            )
            db.commit()
            _log_finished(RunStatus.FAILED, exc.code, exc.turns, exc.usage, started)
            if exc.code.startswith("llm_"):
                raise LLMError(exc.message, code=exc.code) from exc
            raise QueryFailedError(
                f"The assistant could not answer ({exc.code}): {exc.message}"
            ) from exc
        except Exception as exc:
            db.rollback()
            crud.finish_query_run(
                db,
                run.id,
                values=_failed_values("internal_error", f"{type(exc).__name__}: {exc}", None, ctx),
            )
            db.commit()
            raise

        answer = ctx.answer
        assert answer is not None
        finished = crud.finish_query_run(
            db,
            run.id,
            values={
                "status": RunStatus.COMPLETED.value,
                "answer": answer.text,
                "answerable": answer.answerable,
                "numbers_verified": answer.verified,
                "citations": [c.model_dump(mode="json") for c in _citations(db, answer.cited)],
                "steps": [s.model_dump(mode="json") for s in outcome.steps],
                "model": outcome.model or settings.openai_model,
                "prompt_tokens": outcome.usage.prompt_tokens,
                "completion_tokens": outcome.usage.completion_tokens,
                "embedding_tokens": ctx.embedding_tokens,
            },
        )
        db.commit()
        _log_finished(RunStatus.COMPLETED, None, outcome.turns, outcome.usage, started)
    return QueryResponse(
        **_turn(finished).model_dump(),
        conversation_id=conversation.id,
        usage=QueryUsage(
            prompt_tokens=finished.prompt_tokens,
            completion_tokens=finished.completion_tokens,
            embedding_tokens=finished.embedding_tokens,
        ),
    )


def _messages(
    request: QueryRequest,
    memory: list[QueryRun],
    context_entry: IndexEntry | None,
    ctx: QueryToolContext,
    base_currency: str,
    today: date | None,
) -> list[Message]:
    messages: list[Message] = [
        {
            "role": "system",
            "content": prompts.query_system_prompt(
                base_currency, (today or date.today()).isoformat()
            ),
        }
    ]
    if request.document_id is not None:
        fields: dict[str, Any] = (
            _invoice(context_entry)
            if context_entry is not None
            else {"document_id": str(request.document_id), "indexed": False}
        )
        ctx.remember(fields)
        messages.append(
            {"role": "system", "content": prompts.query_context_prompt(json.dumps(fields))}
        )
    for earlier in memory:
        cited = [str(c["document_id"]) for c in earlier.citations]
        messages.append({"role": "user", "content": earlier.question})
        messages.append(
            {"role": "assistant", "content": (earlier.answer or "") + prompts.cited_line(cited)}
        )
    messages.append({"role": "user", "content": request.question})
    return messages


def _citations(db: Session, document_ids: list[str]) -> list[Citation]:
    citations = []
    for value in document_ids:
        entry = retrieval_service.get_entry(db, uuid.UUID(value))
        if entry is None:
            continue
        citations.append(
            Citation(
                document_id=entry.document_id,
                filename=entry.filename,
                vendor=entry.vendor,
                invoice_number=entry.invoice_number,
                invoice_date=entry.invoice_date,
                total_amount=entry.total_amount,
                currency=entry.currency,
                needs_review=entry.needs_review,
            )
        )
    return citations


def _failed_values(
    code: str, message: str, exc: AgentRunError | None, ctx: QueryToolContext
) -> dict[str, Any]:
    usage = exc.usage if exc is not None else TokenUsage()
    return {
        "status": RunStatus.FAILED.value,
        "error_code": code,
        "error": message,
        "steps": [s.model_dump(mode="json") for s in (exc.steps if exc else [])],
        "model": exc.model if exc is not None and exc.model else None,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "embedding_tokens": ctx.embedding_tokens,
    }


def _log_finished(
    status: RunStatus, code: str | None, turns: int, usage: TokenUsage, started: float
) -> None:
    logger.info(
        "query finished",
        extra={
            "status": status.value,
            "error_code": code,
            "turns": turns,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )


def _turn(run: QueryRun) -> QueryTurn:
    duration = None
    if run.finished_at is not None:
        duration = round((run.finished_at - run.started_at).total_seconds() * 1000)
    return QueryTurn(
        turn_id=run.id,
        turn=run.turn,
        question=run.question,
        document_id=run.document_id,
        status=RunStatus(run.status),
        answer=run.answer,
        answerable=run.answerable,
        numbers_verified=run.numbers_verified,
        citations=[Citation.model_validate(c) for c in run.citations],
        steps=[ToolStep.model_validate(s) for s in run.steps],
        error_code=run.error_code,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=duration,
    )


# -- Reads ----------------------------------------------------------------------------------


def get_conversation(db: Session, conversation_id: uuid.UUID) -> ConversationRead:
    conversation = crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise NotFoundError(f"Conversation not found: {conversation_id}")
    return ConversationRead(
        conversation_id=conversation.id,
        created_at=conversation.created_at,
        turns=[_turn(run) for run in crud.list_turns(db, conversation_id)],
    )


_STATIC_QUESTIONS = (
    "How much have we spent with each vendor this year?",
    "Compare an invoice with the vendor's previous invoices",
    "Find invoices for office supplies",
)


def suggestions(db: Session, document_id: uuid.UUID | None = None) -> QuerySuggestions:
    """Example questions built from the indexed data (code, no LLM)."""
    indexed = retrieval_service.stats(db).documents_indexed
    if indexed == 0:
        return QuerySuggestions(indexed_documents=0, questions=list(_STATIC_QUESTIONS))
    questions: list[str] = []
    if document_id is not None:
        entry = retrieval_service.get_entry(db, document_id)
        if entry is not None:
            questions.append(
                f"Compare this invoice with previous {entry.vendor} invoices"
                if entry.vendor
                else "Which earlier invoices are similar to this one?"
            )
    vendors = [name for name, _ in retrieval_service.top_vendors(db, limit=2)]
    if vendors:
        questions.append(f"How much have we spent with {vendors[0]} in total?")
    if len(vendors) > 1:
        questions.append(f"Show the latest invoices from {vendors[1]}")
    questions.append("Which invoices were issued in the last 30 days?")
    return QuerySuggestions(indexed_documents=indexed, questions=questions[:4])

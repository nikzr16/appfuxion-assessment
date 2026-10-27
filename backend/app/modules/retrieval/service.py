"""Retrieval (PRD 0010): the invoice index, embeddings, vendor history, search, similarity.

Everything here is deterministic code except the embedding calls, which go through
``app.core.llm`` with a ``Purpose`` label. This module never imports ``agent``: the agent
calls it (one-way dependency, D1).
"""

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, LLMError
from app.core.llm import LLMClient, Purpose
from app.core.logging import bind_document_id, bind_trace
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.guardrails import service as guardrails_service
from app.modules.retrieval import crud, rules
from app.modules.retrieval.crud import Filters
from app.modules.retrieval.model import InvoiceEmbedding
from app.modules.retrieval.schema import (
    CARD_VERSION,
    EMBEDDING_DIMENSIONS,
    MAX_HISTORY_ITEMS,
    MIN_SIMILARITY,
    BackfillReport,
    HistoryCheck,
    HistoryStats,
    IndexEntry,
    IndexRequest,
    InvoiceHit,
    MatchRule,
    NotIndexedError,
    PreparedEmbedding,
    RetrievalStats,
    SearchFilters,
    SearchResult,
    SimilarInvoices,
    TargetPosition,
    VendorHistory,
    VendorKey,
    VendorNotFoundError,
)
from app.modules.structured_extraction import service as structured_extraction_service
from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.validation import service as validation_service
from app.modules.validation.schema import (
    CurrencyConversionError,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
)

logger = logging.getLogger(__name__)

_MAX_DISTANCE = 1 - MIN_SIMILARITY
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MAX_CANDIDATES = 5


# -- Helpers ----------------------------------------------------------------------------------


def _entry(row: InvoiceEmbedding) -> IndexEntry:
    return IndexEntry.model_validate(
        {**{c: getattr(row, c) for c in IndexEntry.model_fields if c != "embedded"}}
        | {"embedded": row.embedding is not None}
    )


def _hit(row: InvoiceEmbedding, similarity: float | None) -> InvoiceHit:
    return InvoiceHit(
        **_entry(row).model_dump(),
        similarity=None if similarity is None else round(similarity, 3),
    )


def vendor_key(data: InvoiceData) -> VendorKey:
    return VendorKey(
        display=data.vendor,
        name_key=rules.normalise_vendor_name(data.vendor),
        tax_key=rules.normalise_tax_id(data.vendor_tax_id),
    )


def to_base(amount: Decimal | None, currency: str | None, base_currency: str) -> Decimal | None:
    """``amount`` in the base currency with the static rate table; ``None`` if impossible."""
    if amount is None or not currency:
        return None
    if currency == base_currency:
        return rules.money(amount)
    try:
        return validation_service.convert_currency(amount, currency, base_currency).converted_amount
    except CurrencyConversionError:
        return None


def _stats(rows: Sequence[InvoiceEmbedding], base_currency: str) -> HistoryStats:
    totals = [row.total_base for row in rows if row.total_base is not None]
    skipped = [
        row.currency or "unknown"
        for row in rows
        if row.total_amount is not None and row.total_base is None
    ]
    return rules.history_stats(
        totals, count=len(rows), skipped=skipped, base_currency=base_currency
    )


def _match_rule(rows: Sequence[InvoiceEmbedding], tax_key: str | None) -> MatchRule | None:
    if not rows:
        return None
    if tax_key and any(row.vendor_tax_key == tax_key for row in rows):
        return MatchRule.TAX_ID
    return MatchRule.NAME


def _vendor_filters(
    name_key: str | None, tax_key: str | None, base: Filters | None = None
) -> Filters:
    return replace(base or Filters(), vendor=True, vendor_name_key=name_key, vendor_tax_key=tax_key)


# -- Vendor-history checks (D5) ---------------------------------------------------------------


def check_vendor_history(
    db: Session, document_id: uuid.UUID, data: InvoiceData, *, base_currency: str
) -> HistoryCheck:
    """Duplicate invoice number, amount outlier and first-time vendor against the invoices
    uploaded before this document. Deterministic; no LLM call."""
    if data.document_type is DocumentType.UNKNOWN:
        return HistoryCheck(skipped=True, reason="The document is not an invoice or receipt.")
    key = vendor_key(data)
    if not key.known:
        return HistoryCheck(skipped=True, reason="The document has no vendor to compare with.")
    uploaded_at = documents_service.get_document(db, document_id).created_at
    rows = crud.find(
        db,
        _vendor_filters(
            key.name_key,
            key.tax_key,
            Filters(uploaded_before=uploaded_at, exclude_document_id=document_id),
        ),
    )
    vendor = data.vendor or data.vendor_tax_id or "this vendor"
    issues: list[ValidationIssue] = []
    if not rows:
        issues.append(
            ValidationIssue(
                field="vendor",
                code=IssueCode.NEW_VENDOR,
                severity=Severity.INFO,
                message=f"This is the first invoice from {vendor} in the system.",
            )
        )
    else:
        issues.extend(_duplicate_issue(data, rows, vendor))
        issues.extend(_outlier_issue(data, rows, vendor, base_currency))
    return HistoryCheck(
        skipped=False,
        vendor=data.vendor,
        match_rule=_match_rule(rows, key.tax_key),
        earlier_invoices=len(rows),
        issues=issues,
    )


def _duplicate_issue(
    data: InvoiceData, rows: Sequence[InvoiceEmbedding], vendor: str
) -> list[ValidationIssue]:
    number_key = rules.normalise_invoice_number(data.invoice_number)
    if number_key is None:
        return []
    duplicates = [row for row in rows if row.invoice_number_key == number_key]
    if not duplicates:
        return []
    first = duplicates[0]
    details = [first.invoice_date.isoformat() if first.invoice_date else "no date"]
    if first.total_amount is not None:
        details.append(rules.format_money(first.total_amount, first.currency))
    message = (
        f"Invoice number {data.invoice_number} was already used by {vendor} on "
        f"{first.filename} ({', '.join(details)})"
    )
    others = len(duplicates) - 1
    if others:
        message += f" and on {others} other earlier document{'s' if others > 1 else ''}"
    return [
        ValidationIssue(
            field="invoice_number",
            code=IssueCode.DUPLICATE_INVOICE_NUMBER,
            severity=Severity.WARNING,
            message=message + ".",
        )
    ]


def _outlier_issue(
    data: InvoiceData, rows: Sequence[InvoiceEmbedding], vendor: str, base_currency: str
) -> list[ValidationIssue]:
    total = to_base(data.total_amount, data.currency, base_currency)
    stats = _stats(rows, base_currency)
    if total is None or not rules.is_outlier(total, stats):
        return []
    assert stats.median is not None and stats.q1 is not None and stats.q3 is not None
    direction = "above" if total > stats.median else "below"
    converted = (
        f" (converted from {rules.format_money(data.total_amount, data.currency)})"
        if data.total_amount is not None and data.currency != base_currency
        else ""
    )

    def fmt(value: Decimal) -> str:
        return rules.format_money(value, base_currency)

    message = (
        f"The total {fmt(total)}{converted} is far {direction} {vendor}'s usual range "
        f"({fmt(stats.q1)} to {fmt(stats.q3)}, median {fmt(stats.median)}, from "
        f"{stats.with_total} earlier invoices)."
    )
    return [
        ValidationIssue(
            field="total_amount",
            code=IssueCode.AMOUNT_OUTLIER,
            severity=Severity.WARNING,
            message=message,
            expected=stats.median,
            actual=total,
        )
    ]


def merge_report(report: ValidationReport, check: HistoryCheck) -> ValidationReport:
    return validation_service.merge_issues(report, list(check.issues))


# -- Embeddings and the index (D2, D3) --------------------------------------------------------


def _embedding_model() -> str:
    return get_settings().openai_embedding_model


def _embed(
    llm: LLMClient, card: str, model: str
) -> tuple[list[float] | None, str | None, str | None]:
    """(vector, model reported, error code); never raises for an LLM failure."""
    try:
        with bind_trace(purpose=Purpose.EMBEDDING):
            response = llm.embed([card], model=model)
    except LLMError as exc:
        logger.warning("invoice embedding failed", extra={"error_code": exc.code})
        return None, None, exc.code
    vector = response.vectors[0] if response.vectors else None
    if vector is None or len(vector) != EMBEDDING_DIMENSIONS:
        logger.warning("invoice embedding has the wrong size", extra={"model": response.model})
        return None, None, "embedding_dimension_mismatch"
    return vector, response.model, None


def prepare_embedding(
    db: Session, llm: LLMClient, document_id: uuid.UUID, data: InvoiceData
) -> PreparedEmbedding:
    """Build the document's card and its vector; reuse the stored vector when the card and
    model are unchanged (no call). An embedding failure gives ``vector=None``."""
    model = _embedding_model()
    card = rules.build_card(data)
    digest = rules.card_hash(card, model)
    row = crud.get_by_document(db, document_id)
    if row is not None and row.card_hash == digest and row.embedding is not None:
        return PreparedEmbedding(
            card=card,
            card_hash=digest,
            vector=[float(v) for v in row.embedding],
            model=row.embedding_model,
            reused=True,
        )
    vector, reported, error = _embed(llm, card, model)
    return PreparedEmbedding(
        card=card, card_hash=digest, vector=vector, model=reported, reused=False, error_code=error
    )


def index_document(db: Session, request: IndexRequest) -> IndexEntry | None:
    """Write (or replace) the document's index row in the caller's transaction.

    ``unknown`` documents are not indexed; an older row is removed instead (D3).
    """
    if request.data.document_type is DocumentType.UNKNOWN:
        crud.delete_by_document(db, request.document_id)
        return None
    data = request.data
    document = documents_service.get_document(db, request.document_id)
    base_currency = get_settings().base_currency
    embedding = request.embedding
    if embedding is None:
        card = rules.build_card(data)
        embedding = PreparedEmbedding(
            card=card,
            card_hash=rules.card_hash(card, _embedding_model()),
            vector=None,
            model=None,
            reused=False,
        )
    key = vendor_key(data)
    row = crud.upsert(
        db,
        {
            "document_id": request.document_id,
            "run_id": request.run_id,
            "filename": document.filename,
            "uploaded_at": document.created_at,
            "document_type": data.document_type.value,
            "vendor": data.vendor,
            "vendor_tax_id": data.vendor_tax_id,
            "vendor_name_key": key.name_key,
            "vendor_tax_key": key.tax_key,
            "invoice_number": data.invoice_number,
            "invoice_number_key": rules.normalise_invoice_number(data.invoice_number),
            "invoice_date": data.invoice_date,
            "currency": data.currency,
            "total_amount": data.total_amount,
            "total_base": to_base(data.total_amount, data.currency, base_currency),
            "base_currency": base_currency,
            "needs_review": request.needs_review,
            "card": embedding.card,
            "card_hash": embedding.card_hash,
            "card_version": CARD_VERSION,
            "embedding": embedding.vector,
            "embedding_model": embedding.model if embedding.vector is not None else None,
        },
    )
    return _entry(row)


def get_entry(db: Session, document_id: uuid.UUID) -> IndexEntry | None:
    row = crud.get_by_document(db, document_id)
    return _entry(row) if row is not None else None


# -- Similarity (D6, D7) ----------------------------------------------------------------------


def similar_to(
    db: Session,
    document_id: uuid.UUID,
    vector: Sequence[float] | None,
    *,
    k: int,
    earlier_only: bool,
) -> SimilarInvoices:
    """Invoices closest to ``vector`` (the document itself excluded)."""
    if vector is None:
        return SimilarInvoices(document_id=document_id, available=False, items=[])
    before = documents_service.get_document(db, document_id).created_at if earlier_only else None
    pairs = crud.nearest(
        db,
        vector,
        Filters(uploaded_before=before, exclude_document_id=document_id),
        k=k,
        max_distance=_MAX_DISTANCE,
    )
    return SimilarInvoices(
        document_id=document_id,
        available=True,
        items=[_hit(row, 1 - distance) for row, distance in pairs],
    )


def similar_invoices(db: Session, document_id: uuid.UUID, *, k: int = 5) -> SimilarInvoices:
    """``GET /documents/{id}/similar``: uses the stored vector; 409 when not indexed."""
    documents_service.get_document(db, document_id)  # 404 for an unknown document
    row = crud.get_by_document(db, document_id)
    if row is None:
        raise NotIndexedError()
    vector = list(row.embedding) if row.embedding is not None else None
    return similar_to(db, document_id, vector, k=k, earlier_only=False)


# -- Vendor history (D8, D10) -----------------------------------------------------------------


def vendor_history(
    db: Session,
    *,
    document_id: uuid.UUID | None = None,
    invoice_number: str | None = None,
    vendor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> VendorHistory:
    """A vendor's invoices with code-computed statistics, and where one invoice sits."""
    base_currency = get_settings().base_currency
    target = _resolve_target(db, document_id, invoice_number)
    if target is not None:
        name_key, tax_key, display = target.vendor_name_key, target.vendor_tax_key, target.vendor
        if name_key is None and tax_key is None:
            rows: Sequence[InvoiceEmbedding] = [target]
        else:
            rows = crud.find(
                db,
                _vendor_filters(name_key, tax_key, Filters(date_from=date_from, date_to=date_to)),
            )
            if target not in rows:
                rows = [target, *rows]
    else:
        if not vendor or not vendor.strip():
            raise ValueError("vendor_history needs a document_id, an invoice_number or a vendor")
        name_key, tax_key = _vendor_keys_from_text(vendor)
        rows = crud.find(
            db, _vendor_filters(name_key, tax_key, Filters(date_from=date_from, date_to=date_to))
        )
        if not rows:
            raise VendorNotFoundError(
                f"No indexed invoices from a vendor named {vendor!r}.",
                _candidates(db, vendor),
            )
        display = rows[0].vendor

    others = [row for row in rows if target is None or row.document_id != target.document_id]
    stats = _stats(others, base_currency)
    position = _position(target, rows, stats) if target is not None else None
    duplicates = (
        [row for row in others if target.invoice_number_key == row.invoice_number_key]
        if target is not None and target.invoice_number_key
        else []
    )
    return VendorHistory(
        document_id=target.document_id if target is not None else None,
        vendor=display,
        match_rule=_match_rule(others, tax_key) or (MatchRule.NAME if name_key else None),
        base_currency=base_currency,
        invoices=[_entry(row) for row in rows[:MAX_HISTORY_ITEMS]],
        earlier=sum(1 for row in others if target and row.uploaded_at < target.uploaded_at),
        later=sum(1 for row in others if target and row.uploaded_at >= target.uploaded_at),
        stats=stats,
        target=position,
        duplicates=[_entry(row) for row in duplicates],
    )


def _resolve_target(
    db: Session, document_id: uuid.UUID | None, invoice_number: str | None
) -> InvoiceEmbedding | None:
    if document_id is not None:
        documents_service.get_document(db, document_id)  # 404 for an unknown document
        row = crud.get_by_document(db, document_id)
        if row is None:
            raise NotIndexedError()
        return row
    if invoice_number:
        key = rules.normalise_invoice_number(invoice_number)
        rows = crud.find(db, Filters(invoice_number_key=key), limit=1) if key else []
        if not rows:
            raise VendorNotFoundError(f"No indexed invoice has the number {invoice_number!r}.", [])
        return rows[0]
    return None


def _vendor_keys_from_text(text: str) -> tuple[str | None, str | None]:
    """A vendor name, or a tax ID when the text has digits and no spaces."""
    stripped = text.strip()
    tax_key = rules.normalise_tax_id(stripped) if any(c.isdigit() for c in stripped) else None
    return rules.normalise_vendor_name(stripped), tax_key


def _candidates(db: Session, text: str) -> list[str]:
    names = crud.vendor_names_like(db, text.strip(), limit=_MAX_CANDIDATES)
    if names:
        return names
    words = [w for w in re.split(r"\W+", text) if len(w) >= 3]
    found: list[str] = []
    for word in words:
        for name in crud.vendor_names_like(db, word, limit=_MAX_CANDIDATES):
            if name not in found:
                found.append(name)
    return found[:_MAX_CANDIDATES]


def _position(
    target: InvoiceEmbedding, rows: Sequence[InvoiceEmbedding], stats: HistoryStats
) -> TargetPosition:
    total = target.total_base
    diff = pct = None
    position = None
    rank = None
    if total is not None:
        ranked = sorted(
            (row.total_base for row in rows if row.total_base is not None), reverse=True
        )
        rank = ranked.index(total) + 1
        if stats.median is not None:
            diff = rules.money(total - stats.median)
            if stats.median > 0:
                pct = (diff / stats.median * 100).quantize(Decimal("0.1"))
        if stats.q1 is not None and stats.q3 is not None:
            position = "below" if total < stats.q1 else "above" if total > stats.q3 else "within"
    return TargetPosition(
        document_id=target.document_id,
        total_base=total,
        diff_vs_median=diff,
        diff_pct=pct,
        rank=rank,
        position=position,
    )


# -- Search (D7) ------------------------------------------------------------------------------


def _looks_like_identifier(text: str) -> bool:
    stripped = text.strip()
    return bool(_UUID.match(stripped)) or (
        " " not in stripped and any(c.isdigit() for c in stripped)
    )


def search(db: Session, llm: LLMClient, filters: SearchFilters) -> SearchResult:
    """Hybrid search: SQL filters, identifier match, then cosine ranking of ``text``."""
    base_currency = get_settings().base_currency
    sql = Filters(
        invoice_number_key=rules.normalise_invoice_number(filters.invoice_number),
        invoice_number_prefix=True,
        date_from=filters.date_from,
        date_to=filters.date_to,
        currency=filters.currency.strip().upper() if filters.currency else None,
        min_total_base=filters.min_total,
        max_total_base=filters.max_total,
        document_type=filters.document_type.value if filters.document_type else None,
    )
    if filters.vendor and filters.vendor.strip():
        name_key, tax_key = _vendor_keys_from_text(filters.vendor)
        sql = _vendor_filters(name_key, tax_key, sql)
        if crud.count(db, sql) == 0:
            return SearchResult(
                items=[],
                total_matches=0,
                aggregates=None,
                vendor_candidates=_candidates(db, filters.vendor),
            )

    text = (filters.text or "").strip()
    if not text:
        rows = crud.find(db, sql)
        return SearchResult(
            items=[_hit(row, None) for row in rows[: filters.limit]],
            total_matches=len(rows),
            aggregates=_stats(rows, base_currency),
        )

    found: dict[uuid.UUID, InvoiceHit] = {}
    if _looks_like_identifier(text):
        key = rules.normalise_invoice_number(text) or text
        for row in crud.identifier_matches(db, key, text, limit=filters.limit):
            found.setdefault(row.document_id, _hit(row, None))
    note = None
    try:
        with bind_trace(purpose=Purpose.QUERY_EMBEDDING):
            response = llm.embed([text], model=_embedding_model())
    except LLMError as exc:
        logger.warning("query embedding failed", extra={"error_code": exc.code})
        response = None
        note = "Semantic search is unavailable right now; only exact matches are shown."
    embedding_tokens = 0
    if response is not None:
        embedding_tokens = response.usage.prompt_tokens
        for row, distance in crud.nearest(
            db, response.vectors[0], sql, k=filters.limit, max_distance=_MAX_DISTANCE
        ):
            found.setdefault(row.document_id, _hit(row, 1 - distance))
    items = list(found.values())[: filters.limit]
    rows_for_stats = [crud.get_by_document(db, item.document_id) for item in items]
    return SearchResult(
        items=items,
        total_matches=len(items),
        aggregates=_stats([row for row in rows_for_stats if row is not None], base_currency),
        note=note,
        embedding_tokens=embedding_tokens,
    )


# -- Numbers in answers (D8) -----------------------------------------------------------------


def number_tokens(text: str) -> set[str]:
    """Every number in ``text`` in a canonical form, for the Query Agent's number check."""
    return rules.number_tokens(text)


def unverified_numbers(answer: str, known: set[str]) -> list[str]:
    return rules.unverified_numbers(answer, known)


# -- Suggestions, stats, back-fill ------------------------------------------------------------


def top_vendors(db: Session, *, limit: int) -> list[tuple[str, int]]:
    return crud.top_vendors(db, limit=limit)


def stats(db: Session) -> RetrievalStats:
    total, embedded = crud.stats(db)
    return RetrievalStats(
        documents_indexed=total,
        documents_embedded=embedded,
        documents_not_embedded=total - embedded,
    )


def backfill(db: Session, llm: LLMClient) -> BackfillReport:
    """Index completed documents processed before 0010 and fill missing vectors (D12).

    Idempotent. ``needs_review`` is recomputed deterministically from the stored extraction
    (as its run scored it); stored results are never rewritten.
    """
    report = BackfillReport()
    indexed = crud.indexed_document_ids(db)
    tried: set[uuid.UUID] = set()
    documents = []
    offset = 0
    while True:
        page = documents_service.list_documents(
            db, limit=100, offset=offset, status=DocumentStatus.COMPLETED
        )
        documents.extend(page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    for document in sorted(documents, key=lambda d: d.created_at):
        if document.document_id in indexed:
            continue
        with bind_document_id(str(document.document_id)):
            try:
                extraction = structured_extraction_service.get_extraction(db, document.document_id)
            except ConflictError:
                report.skipped += 1
                continue
            data = extraction.data
            if data.document_type is DocumentType.UNKNOWN:
                report.skipped += 1
                continue
            needs_review = None
            if extraction.grounding is not None:
                confidence = guardrails_service.score_confidence(
                    data, extraction.grounding.report, validation_service.validate_invoice(data)
                )
                needs_review = confidence.needs_review if confidence else None
            tried.add(document.document_id)
            embedding = prepare_embedding(db, llm, document.document_id, data)
            index_document(
                db,
                IndexRequest(
                    document_id=document.document_id,
                    run_id=None,
                    data=data,
                    needs_review=needs_review,
                    embedding=embedding,
                ),
            )
            db.commit()
            report.indexed += 1
            if embedding.vector is not None:
                report.embedded += 1
            else:
                report.failed += 1

    for row in crud.missing_embeddings(db):
        if row.document_id in tried:
            continue  # its embedding just failed above
        with bind_document_id(str(row.document_id)):
            vector, model, _ = _embed(llm, row.card, _embedding_model())
        if vector is None:
            report.failed += 1
            continue
        crud.set_embedding(
            db,
            row.document_id,
            vector=vector,
            model=model,
            card_hash=rules.card_hash(row.card, _embedding_model()),
        )
        db.commit()
        report.embedded += 1
    return report

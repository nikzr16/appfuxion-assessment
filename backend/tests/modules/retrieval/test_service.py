import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import LLMError, NotFoundError
from app.core.llm import FakeLLM
from app.core.storage import LocalStorage
from app.modules.observability.model import LlmCall
from app.modules.retrieval import crud, rules
from app.modules.retrieval import service as retrieval_service
from app.modules.retrieval.schema import (
    EMBEDDING_DIMENSIONS,
    IndexRequest,
    MatchRule,
    NotIndexedError,
    SearchFilters,
    VendorNotFoundError,
)
from app.modules.structured_extraction.schema import DocumentType
from app.modules.validation.schema import IssueCode, Severity, ValidationStatus
from app.modules.validation.service import validate_invoice
from tests.modules.retrieval.seed import (
    T0,
    invoice_data,
    make_document,
    seed_invoice,
    set_vector,
    unit,
)


@pytest.fixture
def seed(db_session: Session, storage: LocalStorage):  # type: ignore[no-untyped-def]
    def make(**kwargs):  # type: ignore[no-untyped-def]
        return seed_invoice(db_session, storage, **kwargs)

    return make


def _new_document(db: Session, storage: LocalStorage, index: int = 100) -> uuid.UUID:
    from datetime import timedelta

    return make_document(db, storage, uploaded_at=T0 + timedelta(days=index))


# -- Indexing ---------------------------------------------------------------------------------


def test_index_document_stores_fields_keys_and_base_total(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    document_id = seed(
        vendor="ABC Supplies Sdn. Bhd.",
        vendor_tax_id="c-123",
        invoice_number="inv 1042",
        currency="USD",
        total_amount="100.00",
        vector=unit((0, 1.0)),
    )
    row = crud.get_by_document(db_session, document_id)
    assert row is not None
    assert (row.vendor_name_key, row.vendor_tax_key, row.invoice_number_key) == (
        "abc supplies",
        "C123",
        "INV1042",
    )
    assert row.base_currency == "MYR" and row.total_base is not None and row.total_base > 100
    assert row.card.startswith("Document type: invoice\nVendor: ABC Supplies Sdn. Bhd.")
    assert len(row.embedding) == EMBEDDING_DIMENSIONS
    entry = retrieval_service.get_entry(db_session, document_id)
    assert entry is not None and entry.embedded and entry.needs_review is False


def test_reindexing_replaces_the_row_and_unknown_documents_are_removed(
    db_session: Session, seed
) -> None:
    document_id = seed(total_amount="10.00")
    retrieval_service.index_document(
        db_session,
        IndexRequest(
            document_id=document_id,
            run_id=None,
            data=invoice_data(total_amount="20.00"),
            needs_review=True,
            embedding=None,
        ),
    )
    db_session.commit()
    row = crud.get_by_document(db_session, document_id)
    assert row is not None and row.total_amount == Decimal("20.00") and row.needs_review
    assert row.embedding is None
    assert crud.stats(db_session) == (1, 0)

    unknown = invoice_data(document_type=DocumentType.UNKNOWN.value)
    retrieval_service.index_document(
        db_session,
        IndexRequest(
            document_id=document_id, run_id=None, data=unknown, needs_review=None, embedding=None
        ),
    )
    db_session.commit()
    assert crud.get_by_document(db_session, document_id) is None


def test_prepare_embedding_embeds_the_card_and_reuses_an_unchanged_one(
    db_session: Session, storage: LocalStorage, llm_recorder: None
) -> None:
    document_id = _new_document(db_session, storage)
    fake = FakeLLM()
    data = invoice_data()
    first = retrieval_service.prepare_embedding(db_session, fake, document_id, data)
    assert first.vector is not None and not first.reused
    assert fake.embed_calls == [[rules.build_card(data)]]
    retrieval_service.index_document(
        db_session,
        IndexRequest(
            document_id=document_id, run_id=None, data=data, needs_review=False, embedding=first
        ),
    )
    db_session.commit()

    again = retrieval_service.prepare_embedding(db_session, fake, document_id, data)
    assert again.reused and again.vector == pytest.approx(first.vector)
    assert len(fake.embed_calls) == 1
    changed = retrieval_service.prepare_embedding(
        db_session, fake, document_id, invoice_data(total_amount="5.00")
    )
    assert not changed.reused and len(fake.embed_calls) == 2

    rows = db_session.execute(select(LlmCall)).scalars().all()
    assert [(r.purpose, r.kind) for r in rows] == [("embedding", "embedding")] * 2


def test_an_embedding_failure_gives_no_vector_and_never_raises(
    db_session: Session, storage: LocalStorage
) -> None:
    document_id = _new_document(db_session, storage)
    fake = FakeLLM(max_retries=0)
    fake.embed_error = LLMError("down", code="llm_unavailable")
    prepared = retrieval_service.prepare_embedding(db_session, fake, document_id, invoice_data())
    assert prepared.vector is None and prepared.error_code == "llm_unavailable"


# -- Vendor-history checks (D5) ---------------------------------------------------------------


def _check(db: Session, document_id: uuid.UUID, **fields):  # type: ignore[no-untyped-def]
    return retrieval_service.check_vendor_history(
        db, document_id, invoice_data(**fields), base_currency="MYR"
    )


def test_a_first_invoice_is_a_new_vendor(db_session: Session, storage: LocalStorage) -> None:
    check = _check(db_session, _new_document(db_session, storage))
    assert not check.skipped and check.earlier_invoices == 0
    assert [(i.code, i.severity, i.field) for i in check.issues] == [
        (IssueCode.NEW_VENDOR, Severity.INFO, "vendor")
    ]


def test_unknown_documents_and_missing_vendors_are_skipped(
    db_session: Session, storage: LocalStorage
) -> None:
    document_id = _new_document(db_session, storage)
    assert _check(db_session, document_id, document_type="unknown").skipped
    assert _check(db_session, document_id, vendor=None).skipped


def test_a_duplicate_invoice_number_from_the_same_vendor_is_a_warning(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    seed(index=1, invoice_number="INV-1042", filename="first.pdf", total_amount="1250.00")
    seed(index=2, invoice_number="INV-1042", vendor="Other Shop")  # another vendor
    check = _check(db_session, _new_document(db_session, storage), invoice_number="inv1042")
    assert [i.code for i in check.issues] == [IssueCode.DUPLICATE_INVOICE_NUMBER]
    issue = check.issues[0]
    assert issue.severity is Severity.WARNING and issue.field == "invoice_number"
    assert "first.pdf" in issue.message and "MYR 1,250.00" in issue.message
    assert check.match_rule is MatchRule.NAME and check.earlier_invoices == 1


def test_only_earlier_documents_count_as_history(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    document_id = _new_document(db_session, storage, index=5)
    seed(index=9, invoice_number="INV-1001")  # uploaded later
    check = _check(db_session, document_id)
    assert [i.code for i in check.issues] == [IssueCode.NEW_VENDOR]


def test_vendors_match_by_tax_id_and_never_across_different_tax_ids(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    seed(index=1, vendor="ABC Supplies (M)", vendor_tax_id="C-1", invoice_number="A")
    seed(index=2, vendor="ABC Supplies", vendor_tax_id="C-2", invoice_number="B")
    check = _check(
        db_session,
        _new_document(db_session, storage),
        vendor="ABC Supplies",
        vendor_tax_id="C1",
        invoice_number="B",
    )
    # Matched by tax ID (C1) with a similar name; the same-name vendor with C2 is someone else.
    assert check.match_rule is MatchRule.TAX_ID and check.earlier_invoices == 1
    assert [i.code for i in check.issues] == []


def test_a_shared_tax_id_needs_a_similar_vendor_name(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    # Decision 0012: one tax ID on invoices from different vendors is an extraction error.
    seed(index=1, vendor="Brightlane Logistics", vendor_tax_id="W-1", invoice_number="A")
    seed(index=2, vendor="Acme Trading", vendor_tax_id="W-1", invoice_number="B")
    seed(index=3, vendor=None, vendor_tax_id="W-1", invoice_number="C")
    check = _check(
        db_session,
        _new_document(db_session, storage),
        vendor="Acme Trading Sdn Bhd",
        vendor_tax_id="W1",
        invoice_number="A",
    )
    # Acme's own invoice and the one without a name; not Brightlane's invoice "A".
    assert check.match_rule is MatchRule.TAX_ID and check.earlier_invoices == 2
    assert [i.code for i in check.issues] == []
    other = _check(
        db_session,
        _new_document(db_session, storage, index=101),
        vendor="Cloudnine Hosting",
        vendor_tax_id="W1",
    )
    assert other.earlier_invoices == 1  # only the invoice without a name


def test_an_amount_far_outside_the_vendors_range_is_an_outlier(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    for n, total in enumerate(["900", "1000", "1100", "1150", "1200"]):
        seed(index=n, invoice_number=f"N{n}", total_amount=total)
    document_id = _new_document(db_session, storage)
    check = _check(db_session, document_id, invoice_number="X", total_amount="9800.00")
    assert [i.code for i in check.issues] == [IssueCode.AMOUNT_OUTLIER]
    issue = check.issues[0]
    assert issue.expected == Decimal("1100.00") and issue.actual == Decimal("9800.00")
    assert "far above" in issue.message and "from 5 earlier invoices" in issue.message
    assert _check(db_session, document_id, invoice_number="X", total_amount="1120").issues == []


def test_outliers_need_five_earlier_totals_and_compare_in_the_base_currency(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    for n, total in enumerate(["100", "100", "100", "100"]):
        seed(index=n, invoice_number=f"N{n}", total_amount=total)
    seed(index=4, invoice_number="N4", total_amount="100", currency="XAU")  # not convertible
    document_id = _new_document(db_session, storage)
    assert _check(db_session, document_id, invoice_number="X", total_amount="900").issues == []
    seed(index=5, invoice_number="N5", total_amount="100")
    usd = _check(db_session, document_id, invoice_number="X", total_amount="900", currency="USD")
    assert [i.code for i in usd.issues] == [IssueCode.AMOUNT_OUTLIER]
    assert "converted from USD 900.00" in usd.issues[0].message


def test_merge_report_recomputes_the_status(
    db_session: Session, storage: LocalStorage, seed
) -> None:
    seed(index=1, invoice_number="INV-1001")
    data = invoice_data()
    report = validate_invoice(data)
    assert report.status is ValidationStatus.PASS
    check = retrieval_service.check_vendor_history(
        db_session, _new_document(db_session, storage), data, base_currency="MYR"
    )
    merged = retrieval_service.merge_report(report, check)
    assert merged.status is ValidationStatus.WARN
    assert merged.issues[-1].code is IssueCode.DUPLICATE_INVOICE_NUMBER


# -- Similarity and search (D7) ---------------------------------------------------------------


def test_similar_invoices_rank_by_cosine_drop_weak_ones_and_exclude_itself(
    db_session: Session, seed
) -> None:
    target = seed(index=5, invoice_number="T", vector=unit((0, 1.0)))
    close = seed(index=1, invoice_number="C", vector=unit((0, 0.9), (1, 0.1)))
    medium = seed(index=2, invoice_number="M", vector=unit((0, 0.6), (1, 0.8)))
    seed(index=3, invoice_number="F", vector=unit((1, 1.0)))  # orthogonal: dropped
    seed(index=4, invoice_number="N")  # no vector
    result = retrieval_service.similar_invoices(db_session, target)
    assert result.available
    assert [item.document_id for item in result.items] == [close, medium]
    assert result.items[0].similarity == pytest.approx(0.994, abs=0.001)


def test_similar_invoices_need_an_index_row(db_session: Session, storage: LocalStorage) -> None:
    with pytest.raises(NotIndexedError):
        retrieval_service.similar_invoices(db_session, _new_document(db_session, storage))
    with pytest.raises(NotFoundError):
        retrieval_service.similar_invoices(db_session, uuid.uuid4())


def test_similar_to_can_look_at_earlier_documents_only(db_session: Session, seed) -> None:
    target = seed(index=5, invoice_number="T")
    earlier = seed(index=1, invoice_number="E", vector=unit((0, 1.0)))
    seed(index=9, invoice_number="L", vector=unit((0, 1.0)))
    result = retrieval_service.similar_to(
        db_session, target, unit((0, 1.0)), k=3, earlier_only=True
    )
    assert [item.document_id for item in result.items] == [earlier]
    assert not retrieval_service.similar_to(
        db_session, target, None, k=3, earlier_only=True
    ).available


def test_search_applies_filters_and_aggregates_every_match(db_session: Session, seed) -> None:
    seed(index=1, invoice_number="A1", total_amount="100", invoice_date="2026-01-10")
    seed(index=2, invoice_number="A2", total_amount="300", invoice_date="2026-02-10")
    seed(index=3, invoice_number="A3", total_amount="500", invoice_date="2026-03-10")
    seed(index=4, invoice_number="B1", vendor="Other", total_amount="999")
    result = retrieval_service.search(
        db_session,
        FakeLLM(),
        SearchFilters(vendor="abc supplies", date_from="2026-02-01", limit=1),
    )
    assert result.total_matches == 2 and len(result.items) == 1
    assert result.items[0].invoice_number == "A3"  # newest invoice date first
    assert result.aggregates is not None and result.aggregates.sum == Decimal("800.00")
    over = retrieval_service.search(db_session, FakeLLM(), SearchFilters(min_total=Decimal(400)))
    assert {item.invoice_number for item in over.items} == {"A3", "B1"}


def test_search_suggests_vendors_when_the_vendor_is_unknown(db_session: Session, seed) -> None:
    seed(index=1, vendor="ABC Supplies Sdn Bhd")
    result = retrieval_service.search(db_session, FakeLLM(), SearchFilters(vendor="ABC Supply"))
    assert result.items == [] and result.vendor_candidates == ["ABC Supplies Sdn Bhd"]


def test_search_matches_identifiers_exactly_and_ranks_text_by_similarity(
    db_session: Session, seed, llm_recorder: None
) -> None:
    by_number = seed(index=1, invoice_number="INV-1042", vector=unit((5, 1.0)))
    toner = seed(index=2, invoice_number="T1", vector=unit((0, 1.0)))
    seed(index=3, invoice_number="P1", vector=unit((1, 1.0)))
    fake = FakeLLM(embedder=lambda text: unit((0, 1.0)))
    result = retrieval_service.search(db_session, fake, SearchFilters(text="inv-1042"))
    assert result.items[0].document_id == by_number and result.items[0].similarity is None
    assert [item.document_id for item in result.items[1:]] == [toner]
    semantic = retrieval_service.search(db_session, fake, SearchFilters(text="printer toner"))
    assert [item.document_id for item in semantic.items] == [toner]
    assert semantic.embedding_tokens > 0
    purposes = db_session.execute(select(LlmCall.purpose)).scalars().all()
    assert purposes == ["query_embedding", "query_embedding"]


def test_search_falls_back_to_exact_matches_when_embedding_fails(db_session: Session, seed) -> None:
    by_number = seed(index=1, invoice_number="INV-7", vector=unit((0, 1.0)))
    fake = FakeLLM(max_retries=0)
    fake.embed_error = LLMError("down", code="llm_unavailable")
    result = retrieval_service.search(db_session, fake, SearchFilters(text="INV-7"))
    assert [item.document_id for item in result.items] == [by_number]
    assert result.note is not None


# -- Vendor history (D8, D10) -----------------------------------------------------------------


def test_vendor_history_gives_stats_position_and_duplicates(db_session: Session, seed) -> None:
    for n, total in enumerate(["100", "200", "300", "400"]):
        seed(index=n, invoice_number=f"N{n}", total_amount=total)
    dup = seed(index=5, invoice_number="N1", total_amount="250")
    seed(index=6, vendor="Other", invoice_number="Z")
    history = retrieval_service.vendor_history(db_session, document_id=dup)
    assert history.vendor == "ABC Supplies Sdn Bhd" and history.match_rule is MatchRule.NAME
    assert len(history.invoices) == 5 and (history.earlier, history.later) == (4, 0)
    assert history.stats.count == 4 and history.stats.median == Decimal("250.00")
    assert history.target is not None
    assert history.target.diff_vs_median == Decimal("0.00") and history.target.rank == 3
    assert history.target.position == "within"
    assert [d.invoice_number for d in history.duplicates] == ["N1"]


def test_vendor_history_resolves_invoice_numbers_and_vendor_names(
    db_session: Session, seed
) -> None:
    seed(index=1, invoice_number="INV-9", total_amount="10")
    seed(index=2, invoice_number="INV-10", total_amount="30")
    by_number = retrieval_service.vendor_history(db_session, invoice_number="inv 9")
    assert by_number.target is not None and by_number.stats.count == 1
    by_name = retrieval_service.vendor_history(db_session, vendor="abc supplies")
    assert by_name.target is None and by_name.stats.sum == Decimal("40.00")
    with pytest.raises(VendorNotFoundError) as caught:
        retrieval_service.vendor_history(db_session, vendor="ABC Supply Co")
    assert caught.value.candidates == ["ABC Supplies Sdn Bhd"]
    with pytest.raises(VendorNotFoundError):
        retrieval_service.vendor_history(db_session, invoice_number="nope-1")


def test_vendor_history_keeps_vendors_that_share_a_tax_id_apart(db_session: Session, seed) -> None:
    acme = seed(index=1, vendor="Acme Trading", vendor_tax_id="W-1", total_amount="100")
    seed(index=2, vendor="Acme Trading", vendor_tax_id="W-1", total_amount="300")
    seed(index=3, vendor="Brightlane Logistics", vendor_tax_id="W-1", total_amount="9000")
    history = retrieval_service.vendor_history(db_session, document_id=acme)
    assert history.match_rule is MatchRule.TAX_ID
    assert len(history.invoices) == 2 and history.stats.max == Decimal("300.00")
    # A typed tax ID is one value, not a name: every invoice under it matches.
    by_tax_id = retrieval_service.vendor_history(db_session, vendor="W-1")
    assert by_tax_id.stats.count == 3


def test_vendor_history_of_an_unindexed_document_is_409(
    db_session: Session, storage: LocalStorage
) -> None:
    with pytest.raises(NotIndexedError):
        retrieval_service.vendor_history(db_session, document_id=_new_document(db_session, storage))


# -- Back-fill (D12) and stats ----------------------------------------------------------------


def test_backfill_indexes_completed_documents_and_fills_missing_vectors(
    db_session: Session, storage: LocalStorage, seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.structured_extraction import service as extraction_service
    from app.modules.structured_extraction.schema import ExtractionRead

    plain = _new_document(db_session, storage, index=1)
    unknown = _new_document(db_session, storage, index=2)
    no_extraction = _new_document(db_session, storage, index=3)
    no_vector = seed(index=4, invoice_number="NV")
    datas = {plain: invoice_data(), unknown: invoice_data(document_type="unknown")}

    def fake_get(db: Session, document_id: uuid.UUID) -> ExtractionRead:
        if document_id not in datas:
            from app.core.errors import ConflictError

            raise ConflictError("none", code="extraction_unavailable")
        return ExtractionRead.model_construct(data=datas[document_id], grounding=None)

    monkeypatch.setattr(extraction_service, "get_extraction", fake_get)
    fake = FakeLLM()
    report = retrieval_service.backfill(db_session, fake)
    assert (report.indexed, report.embedded, report.skipped, report.failed) == (1, 2, 2, 0)
    assert crud.get_by_document(db_session, plain) is not None
    assert crud.get_by_document(db_session, unknown) is None
    assert crud.get_by_document(db_session, no_extraction) is None
    row = crud.get_by_document(db_session, no_vector)
    assert row is not None and row.embedding is not None

    again = retrieval_service.backfill(db_session, fake)
    assert (again.indexed, again.embedded) == (0, 0)
    assert retrieval_service.stats(db_session).documents_embedded == 2


def test_stats_count_rows_with_and_without_vectors(db_session: Session, seed) -> None:
    seed(index=1, vector=unit((0, 1.0)))
    with_none = seed(index=2)
    stats = retrieval_service.stats(db_session)
    assert (stats.documents_indexed, stats.documents_embedded, stats.documents_not_embedded) == (
        2,
        1,
        1,
    )
    set_vector(db_session, with_none, unit((1, 1.0)))
    assert retrieval_service.stats(db_session).documents_not_embedded == 0

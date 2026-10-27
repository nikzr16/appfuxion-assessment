import ast
import base64
import io
import uuid
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, LLMError, NotFoundError
from app.core.llm import FakeLLM, LLMCall, LLMResponse, TokenUsage
from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.text_extraction import crud, service
from app.modules.text_extraction.model import DocumentText
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision import images, prompts
from app.modules.vision.schema import PageAnalysis
from tests.modules.text_extraction import samples
from tests.modules.text_extraction.conftest import MakeDocument

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"


def _page(text: str = "INVOICE INV-001 Total RM 123.45") -> PageAnalysis:
    return PageAnalysis(tables=[], blocks=[], text=text, legible=True)


def _sent_image(call: LLMCall) -> Image.Image:
    """Decode the JPEG that was attached to a recorded vision call."""
    url = call.messages[1]["content"][1]["image_url"]["url"]
    prefix = "data:image/jpeg;base64,"
    assert url.startswith(prefix)
    return Image.open(io.BytesIO(base64.b64decode(url[len(prefix) :])))


def _row_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(DocumentText)).scalar_one()


def _assert_nothing_saved(db: Session, document_id: uuid.UUID) -> None:
    assert _row_count(db) == 0
    assert documents_service.get_document(db, document_id).status == DocumentStatus.PROCESSING


# -- Pure helpers ---------------------------------------------------------------------


def test_has_text_ignores_whitespace_and_cid_placeholders() -> None:
    assert service._has_text("INVOICE INV-001 Total RM 123.45")
    assert not service._has_text("")
    assert not service._has_text(" \n\t " * 50)
    assert not service._has_text("(cid:3)" * 30)
    assert not service._has_text("(cid:3) (cid:12)\n" * 10 + "short")


def test_has_text_needs_exactly_twenty_characters() -> None:
    assert service._has_text("a" * 20)
    assert not service._has_text("a" * 19)
    assert service._has_text("a " * 20)  # 20 characters once the spaces are removed
    assert not service._has_text("a " * 19)


def test_join_pages_marks_pages_only_when_there_are_several() -> None:
    assert service._join_pages(["only page"], 1) == "only page"
    assert service._join_pages(["one", "", "three"], 3) == (
        "--- Page 1 ---\none\n\n--- Page 2 ---\n\n\n--- Page 3 ---\nthree"
    )


# -- PDF with a text layer ------------------------------------------------------------


def test_text_pdf_uses_the_parser_and_never_calls_the_llm(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.document_id == document_id
    assert result.method == ExtractionMethod.PDF_PARSER
    assert result.page_count == 1
    for line in samples.INVOICE_LINES:
        assert line in result.raw_text
    assert "--- Page" not in result.raw_text
    assert result.model is None
    assert result.prompt_version is None
    assert fake_llm.calls == []
    assert _row_count(db_session) == 1


def test_multi_page_text_pdf_gets_page_markers(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf(pages=3))

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.method == ExtractionMethod.PDF_PARSER
    assert result.page_count == 3
    for number in (1, 2, 3):
        assert f"--- Page {number} ---" in result.raw_text
        assert f"INVOICE INV-001 page {number} of 3" in result.raw_text
    assert result.raw_text.startswith("--- Page 1 ---\n")
    assert fake_llm.calls == []


# -- Vision: scanned PDFs and images --------------------------------------------------


def test_scanned_pdf_uses_one_vision_call_per_page(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))
    fake_llm.queue(_page("first page text"), _page("second page text"))

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.method == ExtractionMethod.VISION
    assert result.page_count == 2
    assert result.raw_text == "--- Page 1 ---\nfirst page text\n\n--- Page 2 ---\nsecond page text"
    assert result.model == "fake-model"
    assert result.prompt_version == prompts.PROMPT_VERSION == "vision.v1"
    assert len(fake_llm.calls) == 2
    for number, call in enumerate(fake_llm.calls, start=1):
        assert call.vision is True
        assert call.response_format is PageAnalysis
        assert call.temperature == 0
        assert call.messages[0] == {"role": "system", "content": prompts.SYSTEM_PROMPT}
        text_part, image_part = call.messages[1]["content"]
        assert text_part == {"type": "text", "text": f"Transcribe page {number} of 2."}
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert image_part["image_url"]["detail"] == "high"
        assert _sent_image(call).format == "JPEG"


def test_mixed_pdf_goes_through_vision_as_a_whole(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.mixed_pdf())
    fake_llm.queue(_page("page one"), _page("page two"))

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.method == ExtractionMethod.VISION
    assert result.page_count == 2
    assert len(fake_llm.calls) == 2


@pytest.mark.parametrize(
    ("content_type", "data"),
    [(PNG, samples.png_invoice()), (JPEG, samples.jpg_invoice())],
    ids=["png", "jpg"],
)
def test_images_use_vision_with_one_page(
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
    content_type: str,
    data: bytes,
) -> None:
    document_id = make_document(content_type, data)
    fake_llm.queue(_page("  receipt text \n"))

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.method == ExtractionMethod.VISION
    assert result.page_count == 1
    assert result.raw_text == "receipt text"
    assert len(fake_llm.calls) == 1
    assert fake_llm.calls[0].messages[1]["content"][0]["text"] == "Transcribe page 1 of 1."


def test_oversized_image_is_downscaled_before_sending(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(JPEG, samples.jpg_invoice(width=4000, height=3000))
    fake_llm.queue(_page())

    service.extract_text(db_session, storage, fake_llm, document_id)

    sent = _sent_image(fake_llm.calls[0])
    assert max(sent.size) == images.MAX_IMAGE_SIDE
    assert sent.size == (2048, 1536)  # aspect ratio kept


def test_exif_rotated_image_is_sent_upright(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    data = samples.jpg_invoice(width=600, height=300, exif_orientation=6)
    assert Image.open(io.BytesIO(data)).size == (600, 300)
    document_id = make_document(JPEG, data)
    fake_llm.queue(_page())

    service.extract_text(db_session, storage, fake_llm, document_id)

    assert _sent_image(fake_llm.calls[0]).size == (300, 600)


def test_transparent_png_is_flattened_onto_white(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.transparent_png())
    fake_llm.queue(_page())

    service.extract_text(db_session, storage, fake_llm, document_id)

    sent = _sent_image(fake_llm.calls[0]).convert("RGB")
    assert min(sent.getpixel((2, 2))) > 240


def test_vision_pages_beyond_the_cap_are_skipped(
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(get_settings(), "vision_max_pages", 5)
    document_id = make_document(PDF, samples.scanned_pdf(pages=7))
    fake_llm.queue(*[_page(f"text {n}") for n in range(1, 6)])

    with caplog.at_level("WARNING"):
        result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert len(fake_llm.calls) == 5
    assert result.page_count == 7
    assert "--- Page 5 ---\ntext 5" in result.raw_text
    assert "--- Page 6 ---" not in result.raw_text
    capped = [r for r in caplog.records if r.getMessage() == "vision page cap applied"]
    assert len(capped) == 1
    assert (capped[0].pages_total, capped[0].pages_sent) == (7, 5)  # type: ignore[attr-defined]


def test_empty_vision_page_keeps_its_marker(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))
    fake_llm.queue(PageAnalysis(tables=[], blocks=[], text="", legible=False), _page("page two"))

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.raw_text == "--- Page 1 ---\n\n\n--- Page 2 ---\npage two"


def test_no_database_transaction_is_open_during_vision_calls(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    in_transaction: list[bool] = []

    class ProbingLLM(FakeLLM):
        def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
            in_transaction.append(db_session.in_transaction())
            return super().complete(*args, **kwargs)

    llm = ProbingLLM([_page(), _page()])
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))

    service.extract_text(db_session, storage, llm, document_id)

    assert in_transaction == [False, False]


# -- Idempotence and force ------------------------------------------------------------


def test_second_call_returns_the_same_row_without_new_llm_calls(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.png_invoice())
    fake_llm.queue(_page("first"))

    first = service.extract_text(db_session, storage, fake_llm, document_id)
    second = service.extract_text(db_session, storage, fake_llm, document_id)

    assert second == first
    assert len(fake_llm.calls) == 1
    assert _row_count(db_session) == 1


def test_force_replaces_the_row_in_place(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.png_invoice())
    fake_llm.queue(_page("first"), _page("second"))

    first = service.extract_text(db_session, storage, fake_llm, document_id)
    second = service.extract_text(db_session, storage, fake_llm, document_id, force=True)

    assert len(fake_llm.calls) == 2
    assert second.id == first.id
    assert second.raw_text == "second"
    assert second.created_at == first.created_at
    assert second.updated_at > first.updated_at
    assert _row_count(db_session) == 1


def test_force_can_switch_the_method_and_clear_model_fields(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    # An earlier vision result for the same document, e.g. from an older prompt version.
    crud.upsert(
        db_session,
        values={
            "document_id": document_id,
            "raw_text": "old vision text",
            "method": "vision",
            "page_count": 1,
            "model": "old-model",
            "prompt_version": "text_extraction.v0",
        },
        overwrite=False,
    )
    db_session.commit()

    result = service.extract_text(db_session, storage, fake_llm, document_id, force=True)

    assert result.method == ExtractionMethod.PDF_PARSER
    assert result.model is None
    assert result.prompt_version is None
    assert "INVOICE INV-001" in result.raw_text


def test_losing_a_race_returns_the_winners_row(
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = make_document(PNG, samples.png_invoice())
    fake_llm.queue(_page("winner"), _page("loser"))
    winner = service.extract_text(db_session, storage, fake_llm, document_id)

    # The idempotence check misses once, as if the winner committed just after it.
    real = crud.get_by_document
    lookups: list[uuid.UUID] = []

    def missing_once(db: Session, document_id: uuid.UUID) -> DocumentText | None:
        lookups.append(document_id)
        return None if len(lookups) == 1 else real(db, document_id)

    monkeypatch.setattr(crud, "get_by_document", missing_once)

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert len(fake_llm.calls) == 2  # it did the work, then lost the insert
    assert result.id == winner.id
    assert result.raw_text == "winner"
    assert _row_count(db_session) == 1


# -- Errors ---------------------------------------------------------------------------


def test_all_pages_illegible_is_no_text_found(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))
    fake_llm.queue(
        PageAnalysis(tables=[], blocks=[], text="", legible=False),
        PageAnalysis(tables=[], blocks=[], text="ghost text", legible=False),
    )

    with pytest.raises(service.TextExtractionError) as caught:
        service.extract_text(db_session, storage, fake_llm, document_id)

    assert caught.value.code == "no_text_found"
    assert caught.value.status_code == 422
    _assert_nothing_saved(db_session, document_id)


def test_nul_characters_are_removed_before_saving(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.png_invoice())
    fake_llm.queue(_page("INVOICE\x00 INV-001"))

    result = service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.raw_text == "INVOICE INV-001"


def test_blank_legible_text_is_no_text_found(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.png_invoice())
    fake_llm.queue(PageAnalysis(tables=[], blocks=[], text="  \n ", legible=True))

    with pytest.raises(service.TextExtractionError) as caught:
        service.extract_text(db_session, storage, fake_llm, document_id)

    assert caught.value.code == "no_text_found"
    _assert_nothing_saved(db_session, document_id)


@pytest.mark.parametrize(
    ("content_type", "data"),
    [
        (PDF, samples.corrupt_pdf()),
        (PDF, samples.encrypted_pdf()),
        (PNG, b"\x89PNG\r\n\x1a\n" + b"not really a png" * 10),
        (JPEG, b"\xff\xd8\xff\xe0" + b"not really a jpeg" * 10),
    ],
    ids=["corrupt-pdf", "encrypted-pdf", "corrupt-png", "corrupt-jpeg"],
)
def test_unopenable_files_are_unreadable_documents(
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
    content_type: str,
    data: bytes,
) -> None:
    document_id = make_document(content_type, data)

    with pytest.raises(service.TextExtractionError) as caught:
        service.extract_text(db_session, storage, fake_llm, document_id)

    assert caught.value.code == "unreadable_document"
    assert caught.value.status_code == 422
    assert fake_llm.calls == []
    _assert_nothing_saved(db_session, document_id)


def test_missing_stored_file_is_an_unreadable_document(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    source = documents_service.get_document_source(db_session, document_id)
    storage.delete(source.storage_key)

    with pytest.raises(service.TextExtractionError) as caught:
        service.extract_text(db_session, storage, fake_llm, document_id)

    assert caught.value.code == "unreadable_document"
    _assert_nothing_saved(db_session, document_id)


def test_llm_failure_passes_through_and_saves_nothing(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))
    fake_llm.queue(_page("page one"), LLMError("upstream down"))

    with pytest.raises(LLMError) as caught:
        service.extract_text(db_session, storage, fake_llm, document_id)

    assert caught.value.code == "llm_error"
    _assert_nothing_saved(db_session, document_id)


def test_unparsed_vision_reply_is_an_llm_error(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.png_invoice())
    fake_llm.queue(LLMResponse(content=None, usage=TokenUsage(), model="fake-model", parsed=None))

    with pytest.raises(LLMError):
        service.extract_text(db_session, storage, fake_llm, document_id)

    _assert_nothing_saved(db_session, document_id)


def test_extract_text_raises_not_found_for_an_unknown_document(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM
) -> None:
    with pytest.raises(NotFoundError):
        service.extract_text(db_session, storage, fake_llm, uuid.uuid4())


def test_extract_text_never_changes_the_document_status(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())

    service.extract_text(db_session, storage, fake_llm, document_id)

    document = documents_service.get_document(db_session, document_id)
    assert document.status == DocumentStatus.PROCESSING


# -- get_text -------------------------------------------------------------------------


def test_get_text_returns_the_saved_row(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    extracted = service.extract_text(db_session, storage, fake_llm, document_id)

    assert service.get_text(db_session, document_id) == extracted


def test_find_text_returns_the_row_or_none_without_extracting(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())

    assert service.find_text(db_session, document_id) is None
    assert service.find_text(db_session, uuid.uuid4()) is None

    extracted = service.extract_text(db_session, storage, fake_llm, document_id)
    assert service.find_text(db_session, document_id) == extracted


def test_get_text_for_a_processing_document_is_not_ready(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())

    with pytest.raises(ConflictError) as caught:
        service.get_text(db_session, document_id)

    assert caught.value.code == "text_not_ready"
    assert caught.value.status_code == 409


def test_get_text_for_a_failed_document_includes_its_error(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    documents_service.mark_failed(db_session, document_id, "TextExtractionError: no luck")
    db_session.commit()

    with pytest.raises(ConflictError) as caught:
        service.get_text(db_session, document_id)

    assert caught.value.code == "text_unavailable"
    assert "TextExtractionError: no luck" in caught.value.message


def test_get_text_for_a_completed_document_without_text_is_unavailable(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    documents_service.mark_completed(db_session, document_id)
    db_session.commit()

    with pytest.raises(ConflictError) as caught:
        service.get_text(db_session, document_id)

    assert caught.value.code == "text_unavailable"


def test_get_text_raises_not_found_for_an_unknown_document(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.get_text(db_session, uuid.uuid4())


# -- Layering -------------------------------------------------------------------------


def test_module_never_imports_documents_crud_or_model() -> None:
    module_dir = Path(service.__file__).parent
    forbidden = {"app.modules.documents.crud", "app.modules.documents.model"}
    offenders: list[str] = []
    for path in module_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module} | {f"{node.module}.{alias.name}" for alias in node.names}
            else:
                continue
            offenders += [f"{path.name}: {name}" for name in names & forbidden]
    assert offenders == []


def test_service_does_not_import_fastapi() -> None:
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "fastapi" not in source

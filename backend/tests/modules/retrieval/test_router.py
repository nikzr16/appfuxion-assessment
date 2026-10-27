"""HTTP: GET /documents/{id}/similar and GET /documents/{id}/vendor-history."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.storage import LocalStorage
from tests.modules.retrieval.seed import T0, make_document, seed_invoice, unit


def test_similar_invoices_route(
    client: TestClient, db_session: Session, storage: LocalStorage
) -> None:
    target = seed_invoice(db_session, storage, index=3, invoice_number="T", vector=unit((0, 1.0)))
    close = seed_invoice(
        db_session, storage, index=1, invoice_number="C", vector=unit((0, 0.9), (1, 0.1))
    )

    response = client.get(f"/api/documents/{target}/similar", params={"limit": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert [item["document_id"] for item in body["items"]] == [str(close)]
    assert body["items"][0]["similarity"] == 0.994
    assert body["items"][0]["total_amount"] == "1000.00"
    assert client.get(f"/api/documents/{target}/similar", params={"limit": 21}).status_code == 422


def test_vendor_history_route(
    client: TestClient, db_session: Session, storage: LocalStorage
) -> None:
    seed_invoice(db_session, storage, index=1, invoice_number="A", total_amount="100")
    target = seed_invoice(db_session, storage, index=2, invoice_number="A", total_amount="300")

    response = client.get(f"/api/documents/{target}/vendor-history")

    assert response.status_code == 200
    body = response.json()
    assert body["vendor"] == "ABC Supplies Sdn Bhd" and body["match_rule"] == "name"
    assert (body["earlier"], body["later"]) == (1, 0)
    assert body["stats"]["median"] == "100.00"
    assert body["target"]["diff_vs_median"] == "200.00"
    assert [d["invoice_number"] for d in body["duplicates"]] == ["A"]


def test_routes_say_not_indexed_and_not_found(
    client: TestClient, db_session: Session, storage: LocalStorage
) -> None:
    plain = make_document(db_session, storage, uploaded_at=T0)
    for path in ("similar", "vendor-history"):
        response = client.get(f"/api/documents/{plain}/{path}")
        assert response.status_code == 409 and response.json()["error"]["code"] == "not_indexed"
        assert client.get(f"/api/documents/{uuid.uuid4()}/{path}").status_code == 404
        assert client.get(f"/api/documents/not-a-uuid/{path}").status_code == 422

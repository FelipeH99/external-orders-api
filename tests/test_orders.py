def valid_payload(**overrides):
    payload = {
        "external_id": "EXT-001",
        "cliente": "Acme SA",
        "fecha": "2026-08-11T10:30:00",
        "lineas": [
            {"sku": "SKU-001", "cantidad": 2, "precio": "10.50"},
        ],
    }
    payload.update(overrides)
    return payload


def test_valid_order_creates_order(client):
    response = client.post("/orders/external", json=valid_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["external_id"] == "EXT-001"
    assert body["customer"] == "Acme SA"
    assert len(body["lines"]) == 1
    attempts = client.get("/sync-attempts").json()
    assert len(attempts) == 1
    assert attempts[0]["external_id"] == "EXT-001"
    assert attempts[0]["result"] == "success"
    assert attempts[0]["error_message"] is None


def test_order_accepts_internal_line_field_names_for_compatibility(client):
    payload = valid_payload(
        external_id="EXT-ENGLISH-FIELDS",
        lineas=[{"sku": "SKU-001", "quantity": 2, "price": "10.50"}],
    )

    response = client.post("/orders/external", json=payload)

    assert response.status_code == 201
    assert response.json()["lines"][0]["quantity"] == 2


def test_order_with_unknown_sku_is_not_created_and_records_attempt(client):
    payload = valid_payload(
        external_id="EXT-UNKNOWN",
        lineas=[{"sku": "SKU-404", "quantity": 1, "price": "99.00"}],
    )

    response = client.post("/orders/external", json=payload)

    assert response.status_code == 400
    assert client.get("/orders").json() == []
    attempts = client.get("/sync-attempts").json()
    assert attempts[-1]["result"] == "failed"
    assert "SKU-404" in attempts[-1]["error_message"]


def test_duplicate_external_id_does_not_create_second_order(client):
    payload = valid_payload()

    first_response = client.post("/orders/external", json=payload)
    second_response = client.post("/orders/external", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert len(client.get("/orders").json()) == 1
    attempts = client.get("/sync-attempts").json()
    assert [attempt["result"] for attempt in attempts] == ["success", "duplicate"]


def test_integrity_error_on_external_id_is_treated_as_duplicate():
    from sqlalchemy.exc import IntegrityError

    from app import models, schemas, services

    class ScalarResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeSession:
        def __init__(self, existing_order):
            self.added = []
            self.commit_calls = 0
            self.existing_order = existing_order
            self.rolled_back = False

        def scalar(self, _statement):
            if self.rolled_back:
                return self.existing_order
            return None

        def scalars(self, _statement):
            return ScalarResult(
                [models.Product(id=1, sku="SKU-001", name="Keyboard")]
            )

        def add(self, item):
            self.added.append(item)

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls == 1:
                raise IntegrityError("insert", {}, Exception("unique constraint"))

        def rollback(self):
            self.rolled_back = True

        def refresh(self, _item):
            pass

    payload = schemas.ExternalOrderCreate.model_validate(
        valid_payload(external_id="EXT-RACE")
    )
    existing_order = models.Order(
        id=1,
        external_id="EXT-RACE",
        customer="Acme SA",
        order_date=payload.order_date,
        lines=[],
    )
    db = FakeSession(existing_order)

    result = services.process_external_order(db, payload)

    assert result.created is False
    assert result.order is existing_order
    assert db.rolled_back is True
    assert any(
        isinstance(item, models.SyncAttempt)
        and item.result == models.SyncResult.duplicate
        for item in db.added
    )


def test_order_with_multiple_products(client):
    payload = valid_payload(
        external_id="EXT-MULTI",
        lineas=[
            {"sku": "SKU-001", "quantity": 1, "price": "10.00"},
            {"sku": "SKU-002", "quantity": 3, "price": "5.25"},
        ],
    )

    response = client.post("/orders/external", json=payload)

    assert response.status_code == 201
    assert len(response.json()["lines"]) == 2


def test_order_can_include_same_sku_in_multiple_lines(client):
    payload = valid_payload(
        external_id="EXT-REPEATED-SKU",
        lineas=[
            {"sku": "SKU-001", "quantity": 1, "price": "10.00"},
            {"sku": "SKU-001", "quantity": 2, "price": "9.50"},
        ],
    )

    response = client.post("/orders/external", json=payload)

    assert response.status_code == 201
    assert len(response.json()["lines"]) == 2


def test_invalid_payload_records_failed_attempt(client):
    response = client.post(
        "/orders/external",
        json={
            "external_id": "EXT-INVALID",
            "cliente": "",
            "fecha": "not-a-date",
            "lineas": [],
        },
    )

    assert response.status_code == 422
    attempts = client.get("/sync-attempts").json()
    assert attempts[-1]["external_id"] == "EXT-INVALID"
    assert attempts[-1]["result"] == "failed"


def test_validation_errors_outside_order_endpoint_do_not_create_sync_attempts(client):
    response = client.get("/orders/not-an-int")

    assert response.status_code == 422
    assert client.get("/sync-attempts").json() == []


def test_can_query_sync_attempts(client):
    client.post("/orders/external", json=valid_payload(external_id="EXT-HISTORY"))

    response = client.get("/sync-attempts")

    assert response.status_code == 200
    assert response.json()[0]["external_id"] == "EXT-HISTORY"


def test_can_query_products(client):
    response = client.get("/products")

    assert response.status_code == 200
    assert {product["sku"] for product in response.json()} == {
        "SKU-001",
        "SKU-002",
        "SKU-003",
    }

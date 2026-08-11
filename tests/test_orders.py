def valid_payload(**overrides):
    payload = {
        "external_id": "EXT-001",
        "cliente": "Acme SA",
        "fecha": "2026-08-11T10:30:00",
        "lineas": [
            {"sku": "SKU-001", "quantity": 2, "price": "10.50"},
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

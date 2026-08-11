from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas


class OrderProcessingError(Exception):
    pass


def record_attempt(
    db: Session,
    *,
    external_id: str | None,
    result: models.SyncResult,
    error_message: str | None = None,
) -> models.SyncAttempt:
    attempt = models.SyncAttempt(
        external_id=external_id,
        result=result,
        error_message=error_message,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def process_external_order(
    db: Session,
    payload: schemas.ExternalOrderCreate,
) -> models.Order:
    existing_order = db.scalar(
        select(models.Order).where(models.Order.external_id == payload.external_id)
    )
    if existing_order:
        record_attempt(
            db,
            external_id=payload.external_id,
            result=models.SyncResult.duplicate,
            error_message="external_id already processed",
        )
        return existing_order

    skus = {line.sku for line in payload.lines}
    products = db.scalars(select(models.Product).where(models.Product.sku.in_(skus))).all()
    products_by_sku = {product.sku: product for product in products}
    missing_skus = sorted(skus - set(products_by_sku))

    if missing_skus:
        message = f"Unknown SKU(s): {', '.join(missing_skus)}"
        record_attempt(
            db,
            external_id=payload.external_id,
            result=models.SyncResult.failed,
            error_message=message,
        )
        raise OrderProcessingError(message)

    order = models.Order(
        external_id=payload.external_id,
        customer=payload.customer,
        order_date=payload.order_date,
        lines=[
            models.OrderLine(
                product=products_by_sku[line.sku],
                sku=line.sku,
                quantity=line.quantity,
                price=line.price,
            )
            for line in payload.lines
        ],
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    record_attempt(
        db,
        external_id=payload.external_id,
        result=models.SyncResult.success,
    )
    return order


def seed_products(db: Session) -> None:
    existing_count = db.scalar(select(models.Product).limit(1))
    if existing_count:
        return

    db.add_all(
        [
            models.Product(sku="SKU-001", name="Keyboard"),
            models.Product(sku="SKU-002", name="Mouse"),
            models.Product(sku="SKU-003", name="Monitor"),
        ]
    )
    db.commit()

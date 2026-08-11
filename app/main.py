from collections.abc import Generator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import Base, SessionLocal, engine, get_db
from app.services import OrderProcessingError, process_external_order, record_attempt, seed_products


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed_products(db)
    finally:
        db.close()
    yield


app = FastAPI(title="External Orders API", lifespan=lifespan)


def open_attempt_session() -> tuple[Session, Generator[Session, None, None] | None]:
    override = app.dependency_overrides.get(get_db)
    if override:
        db_generator = override()
        return next(db_generator), db_generator
    return SessionLocal(), None


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    external_id = None
    try:
        body = await request.json()
        external_id = body.get("external_id") if isinstance(body, dict) else None
    except Exception:
        pass

    db, db_generator = open_attempt_session()
    try:
        record_attempt(
            db,
            external_id=external_id,
            result=models.SyncResult.failed,
            error_message=str(exc.errors()),
        )
    finally:
        if db_generator:
            try:
                next(db_generator)
            except StopIteration:
                pass
        else:
            db.close()

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=exc.errors(),
    )


@app.post(
    "/orders/external",
    response_model=schemas.OrderRead,
    status_code=status.HTTP_201_CREATED,
)
def receive_external_order(
    payload: schemas.ExternalOrderCreate,
    db: Session = Depends(get_db),
) -> models.Order:
    try:
        return process_external_order(db, payload)
    except OrderProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@app.get("/orders", response_model=list[schemas.OrderRead])
def list_orders(db: Session = Depends(get_db)) -> list[models.Order]:
    return list(db.scalars(select(models.Order).order_by(models.Order.id)))


@app.get("/orders/{order_id}", response_model=schemas.OrderRead)
def get_order(order_id: int, db: Session = Depends(get_db)) -> models.Order:
    order = db.get(models.Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@app.get("/sync-attempts", response_model=list[schemas.SyncAttemptRead])
def list_sync_attempts(db: Session = Depends(get_db)) -> list[models.SyncAttempt]:
    return list(
        db.scalars(select(models.SyncAttempt).order_by(models.SyncAttempt.attempted_at))
    )


@app.get("/products", response_model=list[schemas.ProductRead])
def list_products(db: Session = Depends(get_db)) -> list[models.Product]:
    return list(db.scalars(select(models.Product).order_by(models.Product.sku)))

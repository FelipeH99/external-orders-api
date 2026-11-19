from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.agent.routes import router as agent_router
from app.database import get_db
from app.init_db import init_db
from app.services import OrderProcessingError, process_external_order, record_attempt


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="External Orders API + Order Agent", lifespan=lifespan)
app.include_router(agent_router)


@contextmanager
def open_attempt_session() -> Generator[Session, None, None]:
    db_generator = app.dependency_overrides.get(get_db, get_db)()
    try:
        yield next(db_generator)
    finally:
        db_generator.close()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.method == "POST" and request.url.path == "/orders/external":
        external_id = None
        try:
            body = await request.json()
            external_id = body.get("external_id") if isinstance(body, dict) else None
        except Exception:
            pass

        with open_attempt_session() as db:
            record_attempt(
                db,
                external_id=external_id,
                result=models.SyncResult.failed,
                error_message=str(exc.errors()),
            )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.post(
    "/orders/external",
    response_model=schemas.OrderRead,
    status_code=status.HTTP_201_CREATED,
)
def receive_external_order(
    payload: schemas.ExternalOrderCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> models.Order:
    try:
        result = process_external_order(db, payload)
    except OrderProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result.order


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

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import SyncResult


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str


class ExternalOrderLineCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class ExternalOrderCreate(BaseModel):
    external_id: str = Field(min_length=1, max_length=128)
    customer: str = Field(min_length=1, max_length=255, alias="cliente")
    order_date: datetime = Field(alias="fecha")
    lines: list[ExternalOrderLineCreate] = Field(min_length=1, alias="lineas")


class OrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    quantity: int
    price: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    customer: str
    order_date: datetime
    lines: list[OrderLineRead]


class SyncAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str | None
    attempted_at: datetime
    result: SyncResult
    error_message: str | None

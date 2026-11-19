from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DraftLine(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    quantity: int | None = Field(default=None, gt=0, le=1000000, strict=True)
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer: str | None = Field(default=None, min_length=1, max_length=255)
    order_date: datetime | None = None
    lines: list[DraftLine] = Field(default_factory=list, max_length=100)


    @field_validator("order_date")
    @classmethod
    def normalize_date(cls, value):
        if value is None:
            return value
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Intake(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=16000)


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    draft: Draft


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    decision: Literal["approve", "reject"]


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    request_id: str
    status: str
    version: int
    source_text: str
    provider: str
    model: str | None
    draft: Draft
    issues: list[str]
    total: str | None
    order_id: int | None
    created_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    detail: str
    created_at: datetime

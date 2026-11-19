from datetime import timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.agent.models import AgentEvent, AgentRun
from app.agent.providers import ExtractionError, Extractor, get_extractor
from app.agent.schemas import Decision, Draft, EventRead, Intake, Revision, RunRead
from app.database import get_db
from app.services import OrderProcessingError, process_external_order

router = APIRouter(prefix="/agent", tags=["Order agent"])


def extractor_dependency() -> Extractor:
    try:
        return get_extractor()
    except ExtractionError as exc:
        raise HTTPException(503, str(exc)) from exc


def get_run(db: Session, run_id: str) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, "Borrador no encontrado")
    return run


def event(db: Session, run_id: str, kind: str, detail: str) -> None:
    db.add(AgentEvent(run_id=run_id, kind=kind, detail=detail[:500]))


def assess(db: Session, draft: Draft) -> tuple[list[str], str | None]:
    """Business rules run in Python, never delegated to the language model."""
    skus = set(db.scalars(select(models.Product.sku)))
    issues = []
    if draft.customer is None:
        issues.append("Falta el cliente.")
    if draft.order_date is None:
        issues.append("Falta la fecha del pedido.")
    if not draft.lines:
        issues.append("Falta al menos una línea de pedido.")
    for i, line in enumerate(draft.lines, start=1):
        if line.sku not in skus:
            issues.append(f"Línea {i}: seleccioná un SKU del catálogo.")
        if line.quantity is None:
            issues.append(f"Línea {i}: falta la cantidad.")
        if line.price is None:
            issues.append(f"Línea {i}: falta el precio unitario.")
    total = None if issues else str(sum((line.quantity * line.price for line in draft.lines), Decimal("0")).quantize(Decimal("0.01")))
    return issues, total


def existing_request(db: Session, payload: Intake) -> AgentRun | None:
    existing = db.scalar(select(AgentRun).where(AgentRun.request_id == payload.request_id))
    if existing and existing.source_text != payload.text:
        raise HTTPException(409, "request_id ya utilizado con otra solicitud")
    return existing


@router.post("/runs", response_model=RunRead, status_code=201)
def intake(payload: Intake, response: Response, db: Session = Depends(get_db),
           extractor: Extractor = Depends(extractor_dependency)):
    existing = existing_request(db, payload)
    if existing:
        response.status_code = 200
        return existing
    catalog = [{"sku": p.sku, "name": p.name} for p in db.scalars(select(models.Product).order_by(models.Product.sku))]
    try:
        draft = extractor.extract(payload.text, catalog)
    except ExtractionError as exc:
        raise HTTPException(503 if extractor.name != "json" else 422, str(exc)) from exc
    issues, total = assess(db, draft)
    run = AgentRun(id=str(uuid4()), request_id=payload.request_id, source_text=payload.text,
                   provider=extractor.name, model=extractor.model,
                   status="needs_input" if issues else "awaiting_approval", version=1,
                   draft=draft.model_dump(mode="json"), issues=issues, total=total)
    db.add(run)
    try:
        db.flush()
        event(db, run.id, "draft_created", "Extracción y validación completadas; no se creó ningún pedido.")
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = existing_request(db, payload)
        if existing is None:
            raise
        response.status_code = 200
        return existing
    db.refresh(run)
    return run


@router.get("/runs/{run_id}", response_model=RunRead)
def read_run(run_id: str, db: Session = Depends(get_db)):
    return get_run(db, run_id)


@router.get("/runs/{run_id}/events", response_model=list[EventRead])
def read_events(run_id: str, db: Session = Depends(get_db)):
    get_run(db, run_id)
    return list(db.scalars(select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.id)))


@router.put("/runs/{run_id}/draft", response_model=RunRead)
def revise(run_id: str, payload: Revision, db: Session = Depends(get_db)):
    get_run(db, run_id)
    issues, total = assess(db, payload.draft)
    changed = db.execute(update(AgentRun).where(
        AgentRun.id == run_id, AgentRun.version == payload.version,
        AgentRun.status.in_(["needs_input", "awaiting_approval"]),
    ).values(draft=payload.draft.model_dump(mode="json"), issues=issues, total=total,
             status="needs_input" if issues else "awaiting_approval", version=payload.version + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "El borrador cambió o ya fue decidido. Volvé a consultarlo.")
    event(db, run_id, "draft_revised", f"Revisión {payload.version + 1}; requiere una nueva aprobación.")
    db.commit()
    db.expire_all()
    return get_run(db, run_id)


@router.post("/runs/{run_id}/decision", response_model=RunRead)
def decide(run_id: str, payload: Decision, db: Session = Depends(get_db)):
    get_run(db, run_id)
    allowed = ["awaiting_approval"] if payload.decision == "approve" else ["needs_input", "awaiting_approval"]
    new_status = "approved" if payload.decision == "approve" else "rejected"
    changed = db.execute(update(AgentRun).where(
        AgentRun.id == run_id, AgentRun.version == payload.version, AgentRun.status.in_(allowed),
    ).values(status=new_status, version=payload.version + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "No se puede decidir esta versión o faltan datos.")
    event(db, run_id, new_status, f"Decisión explícita sobre la versión {payload.version}.")
    db.commit()
    db.expire_all()
    return get_run(db, run_id)


@router.post("/runs/{run_id}/execute", response_model=RunRead)
def execute(run_id: str, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if run.status == "completed":
        return run
    if run.status != "approved":
        raise HTTPException(409, "Se requiere aprobación explícita antes de crear el pedido.")
    # The approved snapshot is immutable. Retries always reuse this external ID.
    payload = schemas.ExternalOrderCreate.model_validate({**run.draft, "external_id": f"agent:{run.id}"})
    event(db, run.id, "execution_started", "Creación idempotente del pedido aprobado.")
    db.commit()
    try:
        result = process_external_order(db, payload)
    except OrderProcessingError as exc:
        event(db, run.id, "execution_failed", str(exc))
        db.commit()
        raise HTTPException(409, str(exc)) from exc
    # Recovery after a crash between order creation and run completion is safe:
    # the existing service returns the same order by external_id on the next call.
    order = result.order
    # Agent drafts are normalized to UTC; SQLite returns the stored UTC as naive.
    stored_date = order.order_date.replace(tzinfo=timezone.utc) if order.order_date.tzinfo is None else order.order_date.astimezone(timezone.utc)
    same_date = stored_date == payload.order_date
    if not same_date or order.customer != payload.customer or [
        (l.sku, l.quantity, l.price) for l in order.lines
    ] != [(l.sku, l.quantity, l.price) for l in payload.lines]:
        event(db, run.id, "execution_conflict", "El external_id corresponde a un pedido diferente.")
        db.commit()
        raise HTTPException(409, "Conflicto con un pedido existente; requiere revisión.")
    run.status = "completed"
    run.order_id = order.id
    event(db, run.id, "completed", f"Pedido {order.id} vinculado al borrador aprobado.")
    db.commit()
    db.refresh(run)
    return run

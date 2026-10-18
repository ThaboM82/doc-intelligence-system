"""
HITL API routes — queue, decide, and inspect human-review items.

Prefix: /api/v1/hitl

Endpoints
---------
POST   /evaluate          Run heuristics without queuing (dry-run / debug)
POST   /queue             Evaluate and enqueue when needs_review is true
GET    /queue             List pending (and optional status filter) items
GET    /queue/{item_id}   Fetch one queue item
POST   /queue/{item_id}/decision   Human approve / reject / modify
GET    /stats             Simple in-memory queue counters

Notes
-----
This uses an in-process memory store suitable for single-instance demos and
tests. For multi-instance production, back the store with Redis/Postgres and
protect mutating routes with admin/editor RBAC.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.hitl.reviewer import (
    HitlDecision,
    evaluate_for_review_detailed,
    should_queue_for_human,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hitl", tags=["HITL"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class QueueStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    modified = "modified"
    skipped = "skipped"  # evaluate said no review needed


class EvaluateRequest(BaseModel):
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.low
    text_content: str = ""
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    document_id: str | None = None
    source: str | None = Field(
        default=None,
        description="Caller tag, e.g. ingest | rag | extract",
    )
    collect_all: bool = False


class EvaluateResponse(BaseModel):
    needs_review: bool
    reason: str
    triggers: list[str] = Field(default_factory=list)
    severity: str = "none"
    confidence_score: float
    risk_level: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueueEnqueueRequest(EvaluateRequest):
    """Same as evaluate, plus optional payload snapshot for the reviewer UI."""

    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque snapshot (answer, chunks, extraction) for humans",
    )
    force_enqueue: bool = Field(
        default=False,
        description="Enqueue even when heuristics pass (manual escalation)",
    )


class QueueItem(BaseModel):
    id: str
    status: QueueStatus
    created_at: float
    updated_at: float
    document_id: str | None = None
    source: str | None = None
    decision: EvaluateResponse
    payload: dict[str, Any] = Field(default_factory=dict)
    human_decision: str | None = None
    human_notes: str | None = None
    reviewer_id: str | None = None


class QueueListResponse(BaseModel):
    items: list[QueueItem]
    total: int


class HumanDecisionRequest(BaseModel):
    decision: QueueStatus = Field(
        ...,
        description="approved | rejected | modified",
    )
    notes: str | None = None
    reviewer_id: str | None = None
    modified_payload: dict[str, Any] | None = Field(
        default=None,
        description="Optional corrected payload when decision=modified",
    )


class QueueStatsResponse(BaseModel):
    pending: int
    approved: int
    rejected: int
    modified: int
    skipped: int
    total: int


# ---------------------------------------------------------------------------
# In-memory store (swap for Redis/DB in production)
# ---------------------------------------------------------------------------

_lock = Lock()
_queue: dict[str, QueueItem] = {}


def _decision_from_hitl(d: HitlDecision) -> EvaluateResponse:
    return EvaluateResponse(
        needs_review=d.needs_review,
        reason=d.reason,
        triggers=list(d.triggers),
        severity=d.severity,
        confidence_score=d.confidence_score,
        risk_level=d.risk_level,
        metadata=dict(d.metadata or {}),
    )


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    summary="Run HITL heuristics without enqueueing",
)
async def evaluate_only(body: EvaluateRequest) -> EvaluateResponse:
    """Dry-run reviewer rules for debugging or pre-checks."""
    detailed = evaluate_for_review_detailed(
        confidence_score=body.confidence_score,
        extracted_data=body.extracted_data,
        risk_level=body.risk_level.value,
        text_content=body.text_content,
        source=body.source,
        document_id=body.document_id,
        collect_all=body.collect_all,
    )
    return _decision_from_hitl(detailed)


@router.post(
    "/queue",
    response_model=QueueItem,
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate and enqueue when review is required",
)
async def enqueue_for_review(body: QueueEnqueueRequest) -> QueueItem:
    """
    Run heuristics; if ``needs_review`` (or ``force_enqueue``), store a pending
    queue item and return it. Otherwise return a skipped item (not pending).
    """
    detailed = evaluate_for_review_detailed(
        confidence_score=body.confidence_score,
        extracted_data=body.extracted_data,
        risk_level=body.risk_level.value,
        text_content=body.text_content,
        source=body.source,
        document_id=body.document_id,
        collect_all=body.collect_all,
    )
    eval_resp = _decision_from_hitl(detailed)
    now = time.time()
    needs = should_queue_for_human(detailed) or body.force_enqueue

    item = QueueItem(
        id=_new_id(),
        status=QueueStatus.pending if needs else QueueStatus.skipped,
        created_at=now,
        updated_at=now,
        document_id=body.document_id,
        source=body.source,
        decision=eval_resp,
        payload=dict(body.payload or {}),
    )

    if needs:
        with _lock:
            _queue[item.id] = item
        logger.info(
            "HITL queued id=%s doc=%s triggers=%s",
            item.id,
            body.document_id,
            eval_resp.triggers,
        )
    else:
        logger.debug("HITL skip id=%s reason=%s", item.id, eval_resp.reason)

    return item


@router.get(
    "/queue",
    response_model=QueueListResponse,
    summary="List HITL queue items",
)
async def list_queue(
    status_filter: QueueStatus | None = Query(
        default=QueueStatus.pending,
        alias="status",
        description="Filter by status; omit logic: default pending. Pass empty not supported — use all via status=pending|approved|...",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> QueueListResponse:
    with _lock:
        items = list(_queue.values())

    if status_filter is not None:
        items = [i for i in items if i.status == status_filter]

    items.sort(key=lambda x: x.created_at, reverse=True)
    total = len(items)
    page = items[offset : offset + limit]
    return QueueListResponse(items=page, total=total)


@router.get(
    "/queue/{item_id}",
    response_model=QueueItem,
    summary="Get one HITL queue item",
)
async def get_queue_item(item_id: str) -> QueueItem:
    with _lock:
        item = _queue.get(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="HITL item not found")
    return item


@router.post(
    "/queue/{item_id}/decision",
    response_model=QueueItem,
    summary="Record human approve / reject / modify",
)
async def apply_human_decision(item_id: str, body: HumanDecisionRequest) -> QueueItem:
    if body.decision not in {
        QueueStatus.approved,
        QueueStatus.rejected,
        QueueStatus.modified,
    }:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="decision must be approved, rejected, or modified",
        )

    with _lock:
        item = _queue.get(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="HITL item not found")
        if item.status != QueueStatus.pending:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Item is not pending (status={item.status})",
            )

        item.status = body.decision
        item.human_decision = body.decision.value
        item.human_notes = body.notes
        item.reviewer_id = body.reviewer_id
        item.updated_at = time.time()
        if body.decision == QueueStatus.modified and body.modified_payload is not None:
            item.payload = dict(body.modified_payload)
        _queue[item_id] = item
        out = item

    logger.info(
        "HITL decision id=%s decision=%s reviewer=%s",
        item_id,
        body.decision.value,
        body.reviewer_id,
    )
    return out


@router.get(
    "/stats",
    response_model=QueueStatsResponse,
    summary="In-memory HITL queue counters",
)
async def queue_stats() -> QueueStatsResponse:
    with _lock:
        items = list(_queue.values())

    counts = {s.value: 0 for s in QueueStatus}
    for i in items:
        counts[i.status.value] = counts.get(i.status.value, 0) + 1

    return QueueStatsResponse(
        pending=counts.get("pending", 0),
        approved=counts.get("approved", 0),
        rejected=counts.get("rejected", 0),
        modified=counts.get("modified", 0),
        skipped=counts.get("skipped", 0),
        total=len(items),
    )


@router.delete(
    "/queue/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a queue item (admin/test utility)",
)
async def delete_queue_item(item_id: str) -> None:
    with _lock:
        if item_id not in _queue:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="HITL item not found")
        del _queue[item_id]
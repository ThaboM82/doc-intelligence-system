"""
HITL application service — evaluate, enqueue, decide, inspect.

Sits between FastAPI routes and the reviewer + store.

Public API
----------
evaluate / evaluate_many
enqueue / enqueue_from_decision
get_item / list_items / list_by_document
apply_decision / reopen_item
delete_item / clear_status
stats / health
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from backend.hitl.reviewer import (
    HitlDecision,
    evaluate_for_review_detailed,
    should_queue_for_human,
)
from backend.hitl.store import (
    QueueStatus,
    get_hitl_store,
    new_item_id,
)

logger = logging.getLogger(__name__)

# Terminal statuses that may be reopened back to pending
_REOPENABLE = frozenset(
    {
        QueueStatus.approved.value,
        QueueStatus.rejected.value,
        QueueStatus.modified.value,
    }
)

_DECISION_ALLOWED = frozenset(
    {
        QueueStatus.approved.value,
        QueueStatus.rejected.value,
        QueueStatus.modified.value,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HitlServiceError(Exception):
    """Base service error."""


class HitlNotFoundError(HitlServiceError):
    """Queue item does not exist."""


class HitlConflictError(HitlServiceError):
    """Invalid state transition (e.g. deciding a non-pending item)."""


class HitlValidationError(HitlServiceError):
    """Bad input from caller."""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _decision_dict(d: HitlDecision) -> dict[str, Any]:
    return {
        "needs_review": d.needs_review,
        "reason": d.reason,
        "triggers": list(d.triggers),
        "severity": d.severity,
        "confidence_score": d.confidence_score,
        "risk_level": d.risk_level,
        "metadata": dict(d.metadata or {}),
    }


def _normalize_risk(risk_level: str | None) -> str:
    r = (risk_level or "low").strip().lower()
    if r not in {"low", "medium", "high", "critical"}:
        return "low"
    return r


def _clamp_confidence(score: Any) -> float:
    try:
        c = float(score)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


def _build_item(
    *,
    decision: HitlDecision,
    needs: bool,
    document_id: str | None,
    source: str | None,
    payload: dict[str, Any] | None,
    item_id: str | None = None,
) -> dict[str, Any]:
    now = time.time()
    return {
        "id": item_id or new_item_id(),
        "status": (
            QueueStatus.pending.value if needs else QueueStatus.skipped.value
        ),
        "created_at": now,
        "updated_at": now,
        "document_id": document_id,
        "source": source,
        "decision": _decision_dict(decision),
        "payload": dict(payload or {}),
        "human_decision": None,
        "human_notes": None,
        "reviewer_id": None,
    }


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------


def evaluate(
    *,
    confidence_score: float,
    risk_level: str = "low",
    text_content: str = "",
    extracted_data: dict[str, Any] | None = None,
    document_id: str | None = None,
    source: str | None = None,
    collect_all: bool = False,
) -> HitlDecision:
    """Run heuristics only (no queue write)."""
    return evaluate_for_review_detailed(
        confidence_score=_clamp_confidence(confidence_score),
        extracted_data=extracted_data or {},
        risk_level=_normalize_risk(risk_level),
        text_content=text_content or "",
        source=source,
        document_id=document_id,
        collect_all=collect_all,
    )


def evaluate_many(
    cases: Iterable[dict[str, Any]],
    *,
    collect_all: bool = False,
) -> list[dict[str, Any]]:
    """
    Batch dry-run.

    Each case dict may include:
      confidence_score, risk_level, text_content, extracted_data,
      document_id, source
    """
    out: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            out.append(
                {
                    "index": i,
                    "error": "case must be a dict",
                    "needs_review": True,
                }
            )
            continue
        d = evaluate(
            confidence_score=case.get("confidence_score", 0.0),
            risk_level=case.get("risk_level", "low"),
            text_content=case.get("text_content", "") or "",
            extracted_data=case.get("extracted_data") or {},
            document_id=case.get("document_id"),
            source=case.get("source"),
            collect_all=collect_all,
        )
        row = _decision_dict(d)
        row["index"] = i
        row["document_id"] = case.get("document_id")
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def enqueue(
    *,
    confidence_score: float,
    risk_level: str = "low",
    text_content: str = "",
    extracted_data: dict[str, Any] | None = None,
    document_id: str | None = None,
    source: str | None = None,
    collect_all: bool = False,
    payload: dict[str, Any] | None = None,
    force_enqueue: bool = False,
    persist_skipped: bool = False,
) -> dict[str, Any]:
    """
    Evaluate and optionally persist a queue item.

    - needs_review or force_enqueue → status=pending (always stored)
    - otherwise → status=skipped (stored only if persist_skipped=True)
    """
    decision = evaluate(
        confidence_score=confidence_score,
        risk_level=risk_level,
        text_content=text_content,
        extracted_data=extracted_data,
        document_id=document_id,
        source=source,
        collect_all=collect_all,
    )
    needs = should_queue_for_human(decision) or force_enqueue
    item = _build_item(
        decision=decision,
        needs=needs,
        document_id=document_id,
        source=source,
        payload=payload,
    )

    if needs:
        stored = get_hitl_store().put(item)
        logger.info(
            "HITL enqueued id=%s doc=%s triggers=%s severity=%s",
            stored["id"],
            document_id,
            decision.triggers,
            decision.severity,
        )
        return stored

    logger.debug(
        "HITL skipped doc=%s reason=%s",
        document_id,
        decision.reason,
    )
    if persist_skipped:
        return get_hitl_store().put(item)
    return item


def enqueue_from_decision(
    decision: HitlDecision,
    *,
    document_id: str | None = None,
    source: str | None = None,
    payload: dict[str, Any] | None = None,
    force_enqueue: bool = False,
    persist_skipped: bool = False,
) -> dict[str, Any]:
    """
    Enqueue using an existing HitlDecision (avoids double evaluation).
    """
    needs = should_queue_for_human(decision) or force_enqueue
    item = _build_item(
        decision=decision,
        needs=needs,
        document_id=document_id,
        source=source,
        payload=payload,
    )
    if needs or persist_skipped:
        return get_hitl_store().put(item)
    return item


def enqueue_from_pipeline(
    *,
    confidence_score: float,
    risk_level: str = "low",
    text_content: str = "",
    extracted_data: dict[str, Any] | None = None,
    document_id: str | None = None,
    source: str = "pipeline",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Convenience for ingest/RAG callers: evaluate + enqueue pending only.
    """
    return enqueue(
        confidence_score=confidence_score,
        risk_level=risk_level,
        text_content=text_content,
        extracted_data=extracted_data,
        document_id=document_id,
        source=source,
        payload=payload,
        force_enqueue=False,
        persist_skipped=False,
        collect_all=True,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_item(item_id: str) -> dict[str, Any]:
    if not item_id or not str(item_id).strip():
        raise HitlValidationError("item_id is required")
    row = get_hitl_store().get(str(item_id).strip())
    if row is None:
        raise HitlNotFoundError(f"HITL item not found: {item_id}")
    return row


def list_items(
    *,
    status: str | None = QueueStatus.pending.value,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    return get_hitl_store().list(status=status, limit=limit, offset=offset)


def list_by_document(
    document_id: str,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return queue rows for a document_id (newest first)."""
    if not document_id:
        raise HitlValidationError("document_id is required")
    rows, _ = get_hitl_store().list(status=status, limit=500, offset=0)
    matched = [r for r in rows if r.get("document_id") == document_id]
    return matched[: max(1, min(limit, 200))]


def stats() -> dict[str, int]:
    return get_hitl_store().stats()


def health() -> dict[str, Any]:
    """Lightweight service health for /ready or admin."""
    try:
        s = stats()
        return {
            "ok": True,
            "store": type(get_hitl_store()).__name__,
            "pending": int(s.get("pending", 0)),
            "total": int(s.get("total", 0)),
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Human decisions
# ---------------------------------------------------------------------------


def apply_decision(
    item_id: str,
    *,
    decision: str,
    notes: str | None = None,
    reviewer_id: str | None = None,
    modified_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Record human outcome: approved | rejected | modified.
    """
    decision_n = (decision or "").strip().lower()
    if decision_n not in _DECISION_ALLOWED:
        raise HitlValidationError(
            f"decision must be one of {sorted(_DECISION_ALLOWED)}, got {decision!r}"
        )

    store = get_hitl_store()
    current = store.get(item_id)
    if current is None:
        raise HitlNotFoundError(f"HITL item not found: {item_id}")
    if current.get("status") != QueueStatus.pending.value:
        raise HitlConflictError(
            f"Item is not pending (status={current.get('status')})"
        )

    fields: dict[str, Any] = {
        "status": decision_n,
        "human_decision": decision_n,
        "human_notes": notes,
        "reviewer_id": reviewer_id,
    }
    if decision_n == QueueStatus.modified.value and modified_payload is not None:
        fields["payload"] = dict(modified_payload)

    updated = store.update(item_id, **fields)
    if updated is None:
        raise HitlNotFoundError(f"HITL item not found: {item_id}")

    logger.info(
        "HITL decision id=%s decision=%s reviewer=%s",
        item_id,
        decision_n,
        reviewer_id,
    )
    return updated


def reopen_item(
    item_id: str,
    *,
    notes: str | None = None,
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    """
    Move an approved/rejected/modified item back to pending.
    """
    store = get_hitl_store()
    current = store.get(item_id)
    if current is None:
        raise HitlNotFoundError(f"HITL item not found: {item_id}")
    if current.get("status") not in _REOPENABLE:
        raise HitlConflictError(
            f"Cannot reopen status={current.get('status')}"
        )

    updated = store.update(
        item_id,
        status=QueueStatus.pending.value,
        human_decision=None,
        human_notes=notes,
        reviewer_id=reviewer_id,
    )
    if updated is None:
        raise HitlNotFoundError(f"HITL item not found: {item_id}")
    logger.info("HITL reopened id=%s reviewer=%s", item_id, reviewer_id)
    return updated


def delete_item(item_id: str) -> None:
    if not get_hitl_store().delete(item_id):
        raise HitlNotFoundError(f"HITL item not found: {item_id}")


def clear_status(status: str = QueueStatus.skipped.value) -> int:
    """
    Delete all items with a given status (maintenance / tests).

    Returns number of deleted rows.
    """
    store = get_hitl_store()
    rows, _ = store.list(status=status, limit=10_000, offset=0)
    n = 0
    for row in rows:
        if store.delete(str(row["id"])):
            n += 1
    logger.info("HITL cleared status=%s count=%s", status, n)
    return n


__all__ = [
    "HitlServiceError",
    "HitlNotFoundError",
    "HitlConflictError",
    "HitlValidationError",
    "evaluate",
    "evaluate_many",
    "enqueue",
    "enqueue_from_decision",
    "enqueue_from_pipeline",
    "get_item",
    "list_items",
    "list_by_document",
    "apply_decision",
    "reopen_item",
    "delete_item",
    "clear_status",
    "stats",
    "health",
]
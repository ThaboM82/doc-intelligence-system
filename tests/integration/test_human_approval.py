"""
tests/test_human_approval.py

Human decision path for HITL queue items:
  approve | reject | modify | reopen | conflict on non-pending
"""

from __future__ import annotations

import pytest

from backend.hitl import service as hitl_service
from backend.hitl.service import (
    HitlConflictError,
    HitlNotFoundError,
    HitlValidationError,
)
from backend.hitl.store import QueueStatus, reset_hitl_store


@pytest.fixture(autouse=True)
def _fresh_store():
    """Isolate queue state per test."""
    reset_hitl_store()
    yield
    reset_hitl_store()


def _enqueue_pending(**kwargs):
    """Force a pending item regardless of heuristic outcome."""
    defaults = dict(
        confidence_score=0.99,
        risk_level="low",
        text_content="clean enterprise text",
        extracted_data={"id": "1"},
        document_id="doc-approval-1",
        source="unit",
        payload={"answer": "draft answer"},
        force_enqueue=True,
    )
    defaults.update(kwargs)
    return hitl_service.enqueue(**defaults)


# ---------------------------------------------------------------------------
# Approve / reject / modify
# ---------------------------------------------------------------------------


def test_approve_pending_item():
    item = _enqueue_pending()
    assert item["status"] == QueueStatus.pending.value

    updated = hitl_service.apply_decision(
        item["id"],
        decision="approved",
        notes="Looks correct",
        reviewer_id="alice",
    )
    assert updated["status"] == "approved"
    assert updated["human_decision"] == "approved"
    assert updated["human_notes"] == "Looks correct"
    assert updated["reviewer_id"] == "alice"

    stored = hitl_service.get_item(item["id"])
    assert stored["status"] == "approved"


def test_reject_pending_item():
    item = _enqueue_pending()
    updated = hitl_service.apply_decision(
        item["id"],
        decision="rejected",
        notes="Policy mismatch",
        reviewer_id="bob",
    )
    assert updated["status"] == "rejected"
    assert updated["human_decision"] == "rejected"
    assert updated["human_notes"] == "Policy mismatch"


def test_modify_pending_item_updates_payload():
    item = _enqueue_pending(payload={"answer": "old"})
    updated = hitl_service.apply_decision(
        item["id"],
        decision="modified",
        notes="Corrected citation",
        reviewer_id="carol",
        modified_payload={"answer": "new", "sources": ["a.pdf"]},
    )
    assert updated["status"] == "modified"
    assert updated["payload"]["answer"] == "new"
    assert updated["payload"]["sources"] == ["a.pdf"]


def test_decision_case_insensitive():
    item = _enqueue_pending()
    updated = hitl_service.apply_decision(item["id"], decision="APPROVED")
    assert updated["status"] == "approved"


# ---------------------------------------------------------------------------
# Validation & conflicts
# ---------------------------------------------------------------------------


def test_invalid_decision_raises():
    item = _enqueue_pending()
    with pytest.raises(HitlValidationError):
        hitl_service.apply_decision(item["id"], decision="maybe")


def test_decision_on_missing_item_raises():
    with pytest.raises(HitlNotFoundError):
        hitl_service.apply_decision("missing-id", decision="approved")


def test_double_decision_raises_conflict():
    item = _enqueue_pending()
    hitl_service.apply_decision(item["id"], decision="approved")
    with pytest.raises(HitlConflictError):
        hitl_service.apply_decision(item["id"], decision="rejected")


def test_cannot_decide_skipped_ephemeral():
    """
    Without force_enqueue, clean high-confidence content is skipped and
    not persisted — get/decision should fail.
    """
    row = hitl_service.enqueue(
        confidence_score=0.99,
        risk_level="low",
        text_content="harmless operations note",
        extracted_data={},
        force_enqueue=False,
        persist_skipped=False,
    )
    assert row["status"] == QueueStatus.skipped.value
    # Not in store → not found
    with pytest.raises(HitlNotFoundError):
        hitl_service.apply_decision(row["id"], decision="approved")


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------


def test_reopen_approved_item():
    item = _enqueue_pending()
    hitl_service.apply_decision(item["id"], decision="approved", reviewer_id="alice")
    reopened = hitl_service.reopen_item(
        item["id"],
        notes="Need second look",
        reviewer_id="dave",
    )
    assert reopened["status"] == "pending"
    assert reopened["human_decision"] is None
    # Can decide again
    final = hitl_service.apply_decision(item["id"], decision="rejected")
    assert final["status"] == "rejected"


def test_reopen_pending_raises():
    item = _enqueue_pending()
    with pytest.raises(HitlConflictError):
        hitl_service.reopen_item(item["id"])


# ---------------------------------------------------------------------------
# List / stats after decisions
# ---------------------------------------------------------------------------


def test_list_and_stats_reflect_decisions():
    a = _enqueue_pending(document_id="d1")
    b = _enqueue_pending(document_id="d2")
    hitl_service.apply_decision(a["id"], decision="approved")
    hitl_service.apply_decision(b["id"], decision="rejected")

    pending, p_total = hitl_service.list_items(status="pending")
    approved, a_total = hitl_service.list_items(status="approved")
    rejected, r_total = hitl_service.list_items(status="rejected")

    assert p_total == 0
    assert a_total == 1
    assert r_total == 1
    assert approved[0]["id"] == a["id"]
    assert rejected[0]["id"] == b["id"]

    st = hitl_service.stats()
    assert st["approved"] >= 1
    assert st["rejected"] >= 1
    assert st["pending"] == 0


def test_list_by_document_after_modify():
    item = _enqueue_pending(document_id="doc-xyz")
    hitl_service.apply_decision(
        item["id"],
        decision="modified",
        modified_payload={"answer": "fixed"},
    )
    rows = hitl_service.list_by_document("doc-xyz")
    assert len(rows) >= 1
    assert rows[0]["payload"]["answer"] == "fixed"
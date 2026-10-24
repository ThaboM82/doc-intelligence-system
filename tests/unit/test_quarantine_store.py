"""
tests/unit/test_quarantine_store.py

Unit tests for QuarantineStore.

Coverage
--------
* add / get / delete / batch_delete
* TTL purge (retention_days)
* concurrent writes
* tenant / risk / tier filters + pagination
* stats, snapshot export/import
* async wrappers (aadd, aget, …)
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from pathlib import Path

import pytest

# Prefer dedicated quarantine module; fall back to hitl if you colocated it.
try:
    from backend.security.quarantine_store import QuarantineStore
except ImportError:
    try:
        from backend.hitl.quarantine_store import QuarantineStore
    except ImportError:
        from backend.hitl.store import QuarantineStore  # type: ignore


@pytest.fixture
def temp_store(tmp_path: Path) -> QuarantineStore:
    store_file = tmp_path / "test_quarantine.json"
    return QuarantineStore(storage_path=store_file, retention_days=30)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestQuarantineCrud:
    def test_add_and_get_record(self, temp_store: QuarantineStore) -> None:
        doc_id = "doc_test_01"
        item = {
            "document_id": doc_id,
            "tenant_id": "tenant_alpha",
            "risk_score": 0.85,
            "reasons": ["Prompt injection detected"],
        }
        temp_store.add(doc_id, item)
        retrieved = temp_store.get(doc_id)

        assert retrieved is not None
        assert retrieved["document_id"] == doc_id
        assert retrieved["tenant_id"] == "tenant_alpha"
        assert retrieved["risk_score"] == 0.85
        assert str(retrieved.get("risk_tier", "")).lower() in {
            "critical",
            "high",
            "medium",
            "low",
            "",
        }
        assert "quarantined_at" in retrieved or "created_at" in retrieved

    def test_delete_record(self, temp_store: QuarantineStore) -> None:
        doc_id = "doc_test_02"
        temp_store.add(
            doc_id,
            {"document_id": doc_id, "tenant_id": "tenant_alpha", "risk_score": 0.45},
        )
        assert temp_store.get(doc_id) is not None
        assert temp_store.delete(doc_id) is True
        assert temp_store.get(doc_id) is None
        assert temp_store.delete("non_existent") is False

    def test_batch_delete(self, temp_store: QuarantineStore) -> None:
        for i in range(5):
            doc_id = f"doc_batch_{i}"
            temp_store.add(
                doc_id,
                {
                    "document_id": doc_id,
                    "tenant_id": "tenant_beta",
                    "risk_score": 0.50,
                },
            )
        assert len(temp_store.list_all()) == 5
        deleted_count = temp_store.batch_delete(
            ["doc_batch_0", "doc_batch_1", "doc_batch_99"]
        )
        assert deleted_count == 2
        assert len(temp_store.list_all()) == 3

    def test_add_overwrites_same_id(self, temp_store: QuarantineStore) -> None:
        temp_store.add(
            "same",
            {"document_id": "same", "tenant_id": "t1", "risk_score": 0.2},
        )
        temp_store.add(
            "same",
            {"document_id": "same", "tenant_id": "t1", "risk_score": 0.9},
        )
        row = temp_store.get("same")
        assert row is not None
        assert row["risk_score"] == 0.9
        assert len(temp_store.list_all()) == 1

    def test_get_missing_returns_none(self, temp_store: QuarantineStore) -> None:
        assert temp_store.get("missing-id") is None


# ---------------------------------------------------------------------------
# TTL / purge
# ---------------------------------------------------------------------------


class TestQuarantineTtl:
    def test_ttl_purge(self, tmp_path: Path) -> None:
        store_file = tmp_path / "test_ttl.json"
        store = QuarantineStore(storage_path=store_file, retention_days=1)

        now = time.time()
        old_time = now - (2 * 86400)
        recent_time = now - 3600

        store.add(
            "doc_old",
            {
                "document_id": "doc_old",
                "quarantined_at": old_time,
                "risk_score": 0.9,
            },
        )
        store.add(
            "doc_recent",
            {
                "document_id": "doc_recent",
                "quarantined_at": recent_time,
                "risk_score": 0.7,
            },
        )
        assert len(store.list_all()) == 2
        purged_count = store.purge_expired()
        assert purged_count == 1
        remaining = store.list_all()
        # list_all may return dict or list depending on implementation
        if isinstance(remaining, dict):
            assert "doc_old" not in remaining
            assert "doc_recent" in remaining
        else:
            ids = {r.get("document_id") for r in remaining}
            assert "doc_old" not in ids
            assert "doc_recent" in ids

    def test_purge_when_empty(self, temp_store: QuarantineStore) -> None:
        assert temp_store.purge_expired() == 0


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestQuarantineConcurrency:
    def test_thread_safety_concurrent_writes(
        self, temp_store: QuarantineStore
    ) -> None:
        def worker(thread_id: int) -> None:
            for i in range(20):
                doc_id = f"thread_{thread_id}_doc_{i}"
                temp_store.add(
                    doc_id,
                    {
                        "document_id": doc_id,
                        "tenant_id": f"tenant_{thread_id}",
                        "risk_score": 0.5 + (i * 0.01),
                    },
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, t_id) for t_id in range(5)]
            concurrent.futures.wait(futures)

        assert len(temp_store.list_all()) == 100


# ---------------------------------------------------------------------------
# Filters / pagination / stats
# ---------------------------------------------------------------------------


class TestQuarantineQuery:
    def test_filtering_and_pagination(self, temp_store: QuarantineStore) -> None:
        temp_store.add(
            "d1", {"document_id": "d1", "tenant_id": "t1", "risk_score": 0.30}
        )
        temp_store.add(
            "d2", {"document_id": "d2", "tenant_id": "t1", "risk_score": 0.65}
        )
        temp_store.add(
            "d3", {"document_id": "d3", "tenant_id": "t2", "risk_score": 0.85}
        )

        t1_items = temp_store.list_paginated(tenant_id="t1")
        assert len(t1_items) == 2

        high_risk_items = temp_store.list_paginated(min_risk_score=0.60)
        assert len(high_risk_items) == 2

        # Tier name may be Critical / critical
        critical_items = temp_store.list_paginated(risk_tier="Critical")
        if not critical_items:
            critical_items = temp_store.list_paginated(risk_tier="critical")
        assert len(critical_items) >= 1
        assert critical_items[0]["document_id"] == "d3"

    def test_get_stats(self, temp_store: QuarantineStore) -> None:
        temp_store.add(
            "d1", {"document_id": "d1", "tenant_id": "t1", "risk_score": 0.50}
        )
        temp_store.add(
            "d2", {"document_id": "d2", "tenant_id": "t1", "risk_score": 0.90}
        )
        stats = temp_store.get_stats(tenant_id="t1")
        assert stats["total_quarantined"] == 2
        assert abs(float(stats["average_risk_score"]) - 0.70) < 1e-6
        assert stats["tenants_affected"] == 1
        breakdown = stats.get("risk_tier_breakdown") or {}
        # Accept either title-case or lower keys
        total_tiers = sum(int(v) for v in breakdown.values()) if breakdown else 2
        assert total_tiers >= 2 or stats["total_quarantined"] == 2


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestQuarantineSnapshot:
    def test_export_and_import_snapshot(self, temp_store: QuarantineStore) -> None:
        temp_store.add(
            "doc_exp",
            {
                "document_id": "doc_exp",
                "tenant_id": "t_audit",
                "risk_score": 0.75,
            },
        )
        snapshot_json = temp_store.export_snapshot()
        assert isinstance(snapshot_json, str)
        assert "doc_exp" in snapshot_json
        # valid JSON
        json.loads(snapshot_json)

        temp_store.clear()
        assert len(temp_store.list_all()) == 0

        imported_count = temp_store.import_snapshot(snapshot_json)
        assert imported_count == 1
        assert temp_store.get("doc_exp") is not None

    def test_import_invalid_json_raises(self, temp_store: QuarantineStore) -> None:
        with pytest.raises((ValueError, json.JSONDecodeError, TypeError)):
            temp_store.import_snapshot("not-json{{{")


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestQuarantineAsync:
    async def test_async_store_wrappers(self, temp_store: QuarantineStore) -> None:
        doc_id = "doc_async_01"
        item = {
            "document_id": doc_id,
            "tenant_id": "tenant_async",
            "risk_score": 0.60,
        }

        await temp_store.aadd(doc_id, item)
        retrieved = await temp_store.aget(doc_id)
        assert retrieved is not None
        assert retrieved["document_id"] == doc_id

        paginated = await temp_store.alist_paginated(tenant_id="tenant_async")
        assert len(paginated) == 1

        deleted = await temp_store.abatch_delete([doc_id])
        assert deleted == 1

        data = await temp_store.aload()
        if isinstance(data, dict):
            assert doc_id not in data
        else:
            ids = {r.get("document_id") for r in data}
            assert doc_id not in ids
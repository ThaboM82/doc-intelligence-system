"""
tests/test_hitl_store.py

Unit tests for backend.hitl.store.

* In-memory backend: always runs
* Redis backend: only when HITL_REDIS_URL is set and redis is importable
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from typing import Any

import pytest

from backend.hitl.store import (
    InMemoryHitlStore,
    QueueStatus,
    RedisHitlStore,
    create_hitl_store,
    get_hitl_store,
    new_item_id,
    reset_hitl_store,
    set_hitl_store,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem() -> Generator[InMemoryHitlStore, None, None]:
    store = InMemoryHitlStore(max_items=200)
    set_hitl_store(store)
    yield store
    reset_hitl_store()


def _sample(
    *,
    status: str = "pending",
    document_id: str | None = "doc-1",
    source: str | None = "test",
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "status": status,
        "document_id": document_id,
        "source": source,
        "payload": {"k": "v"},
        "decision": {"needs_review": True, "reason": "unit"},
    }
    row.update(extra)
    return row


redis_available = bool(os.getenv("HITL_REDIS_URL"))
try:
    import redis as _redis_mod  # noqa: F401
except ImportError:
    _redis_mod = None
    redis_available = False

requires_redis = pytest.mark.skipif(
    not redis_available,
    reason="Set HITL_REDIS_URL and install redis to run Redis store tests",
)


# ---------------------------------------------------------------------------
# Helpers / factory
# ---------------------------------------------------------------------------


class TestIdsAndFactory:
    def test_new_item_id_unique(self):
        a, b = new_item_id(), new_item_id()
        assert a != b
        assert len(a) >= 32

    def test_create_default_memory(self, monkeypatch):
        monkeypatch.delenv("HITL_STORE_BACKEND", raising=False)
        store = create_hitl_store()
        assert isinstance(store, InMemoryHitlStore)

    def test_create_redis_falls_back_without_package(self, monkeypatch):
        monkeypatch.setenv("HITL_STORE_BACKEND", "redis")
        # Even if redis missing or URL bad, factory must not crash hard for callers
        store = create_hitl_store()
        assert store is not None

    def test_singleton_get_set_reset(self, mem: InMemoryHitlStore):
        assert get_hitl_store() is mem
        fresh = reset_hitl_store()
        assert isinstance(fresh, InMemoryHitlStore)
        assert get_hitl_store() is fresh


# ---------------------------------------------------------------------------
# In-memory CRUD
# ---------------------------------------------------------------------------


class TestInMemoryCrud:
    def test_put_assigns_id_and_timestamps(self, mem: InMemoryHitlStore):
        row = mem.put(_sample())
        assert row["id"]
        assert row["created_at"]
        assert row["updated_at"]
        assert row["status"] == "pending"

    def test_put_preserves_explicit_id(self, mem: InMemoryHitlStore):
        fixed = "fixed-id-001"
        row = mem.put(_sample(id=fixed))
        assert row["id"] == fixed
        assert mem.get(fixed) is not None

    def test_get_missing_returns_none(self, mem: InMemoryHitlStore):
        assert mem.get("does-not-exist") is None

    def test_delete_true_false(self, mem: InMemoryHitlStore):
        row = mem.put(_sample())
        assert mem.delete(row["id"]) is True
        assert mem.delete(row["id"]) is False
        assert mem.get(row["id"]) is None

    def test_exists(self, mem: InMemoryHitlStore):
        row = mem.put(_sample())
        assert mem.exists(row["id"]) is True
        mem.delete(row["id"])
        assert mem.exists(row["id"]) is False

    def test_update_patches_and_bumps_updated_at(self, mem: InMemoryHitlStore):
        row = mem.put(_sample())
        t0 = row["updated_at"]
        time.sleep(0.01)
        updated = mem.update(
            row["id"],
            status=QueueStatus.approved.value,
            human_notes="lgtm",
            reviewer_id="alice",
        )
        assert updated is not None
        assert updated["status"] == "approved"
        assert updated["human_notes"] == "lgtm"
        assert updated["reviewer_id"] == "alice"
        assert updated["updated_at"] >= t0
        assert updated["id"] == row["id"]

    def test_update_cannot_change_id(self, mem: InMemoryHitlStore):
        row = mem.put(_sample())
        updated = mem.update(row["id"], id="hijack")
        assert updated is not None
        assert updated["id"] == row["id"]

    def test_update_missing_returns_none(self, mem: InMemoryHitlStore):
        assert mem.update("missing", status="approved") is None


# ---------------------------------------------------------------------------
# List / filter / stats
# ---------------------------------------------------------------------------


class TestInMemoryQuery:
    def test_list_empty(self, mem: InMemoryHitlStore):
        rows, total = mem.list()
        assert rows == []
        assert total == 0

    def test_list_newest_first(self, mem: InMemoryHitlStore):
        a = mem.put(_sample(document_id="a"))
        time.sleep(0.01)
        b = mem.put(_sample(document_id="b"))
        rows, total = mem.list()
        assert total == 2
        assert rows[0]["id"] == b["id"]
        assert rows[1]["id"] == a["id"]

    def test_list_status_filter(self, mem: InMemoryHitlStore):
        mem.put(_sample(status="pending"))
        mem.put(_sample(status="approved"))
        mem.put(_sample(status="pending"))
        rows, total = mem.list(status="pending")
        assert total == 2
        assert all(r["status"] == "pending" for r in rows)

    def test_list_document_and_source_filter(self, mem: InMemoryHitlStore):
        mem.put(_sample(document_id="d1", source="rag", status="pending"))
        mem.put(_sample(document_id="d1", source="ingest", status="pending"))
        mem.put(_sample(document_id="d2", source="rag", status="pending"))
        rows, total = mem.list(document_id="d1", source="rag")
        assert total == 1
        assert rows[0]["source"] == "rag"

    def test_list_pagination(self, mem: InMemoryHitlStore):
        for i in range(5):
            mem.put(_sample(document_id=f"p-{i}"))
        page1, total = mem.list(limit=2, offset=0)
        page2, _ = mem.list(limit=2, offset=2)
        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        ids = {r["id"] for r in page1 + page2}
        assert len(ids) == 4

    def test_stats_counts(self, mem: InMemoryHitlStore):
        mem.put(_sample(status="pending"))
        mem.put(_sample(status="pending"))
        mem.put(_sample(status="rejected"))
        st = mem.stats()
        assert st["pending"] == 2
        assert st["rejected"] == 1
        assert st["total"] == 3
        assert "max_items" in st

    def test_find_predicate(self, mem: InMemoryHitlStore):
        mem.put(_sample(document_id="x", source="rag"))
        mem.put(_sample(document_id="y", source="ingest"))
        found = mem.find(lambda r: r.get("source") == "rag")
        assert len(found) == 1
        assert found[0]["document_id"] == "x"

    def test_clear(self, mem: InMemoryHitlStore):
        mem.put(_sample())
        mem.put(_sample())
        n = mem.clear()
        assert n == 2
        assert mem.size() == 0


# ---------------------------------------------------------------------------
# Capacity / prune
# ---------------------------------------------------------------------------


class TestInMemoryPrune:
    def test_prune_prefers_skipped(self):
        store = InMemoryHitlStore(max_items=3)
        store.put(_sample(status="skipped", document_id="s1"))
        store.put(_sample(status="skipped", document_id="s2"))
        store.put(_sample(status="pending", document_id="p1"))
        store.put(_sample(status="skipped", document_id="s3"))
        assert store.size() <= 3
        # pending should survive longer than skipped under pressure
        rows, _ = store.list(status="pending")
        assert any(r["document_id"] == "p1" for r in rows)

    def test_size_respects_max(self):
        store = InMemoryHitlStore(max_items=2)
        for i in range(6):
            store.put(_sample(status="approved", document_id=str(i)))
        assert store.size() <= 2


# ---------------------------------------------------------------------------
# Redis (optional)
# ---------------------------------------------------------------------------


@requires_redis
class TestRedisStore:
    @pytest.fixture
    def rstore(self):
        store = RedisHitlStore()
        if not store.ping():
            pytest.skip("Redis not reachable")
        # isolate keys for this test session
        store.prefix = f"hitl:test:{new_item_id()[:8]}"
        yield store
        store.clear()

    def test_ping(self, rstore: RedisHitlStore):
        assert rstore.ping() is True

    def test_put_get_delete(self, rstore: RedisHitlStore):
        row = rstore.put(_sample(document_id="redis-doc"))
        item_id = row["id"]
        got = rstore.get(item_id)
        assert got is not None
        assert got["document_id"] == "redis-doc"
        assert rstore.delete(item_id) is True
        assert rstore.get(item_id) is None

    def test_update_status_and_list(self, rstore: RedisHitlStore):
        row = rstore.put(_sample(status="pending", document_id="rd", source="rag"))
        rstore.update(row["id"], status="approved")
        got = rstore.get(row["id"])
        assert got is not None
        assert got["status"] == "approved"
        rows, total = rstore.list(document_id="rd", status="approved")
        assert total >= 1
        assert rows[0]["id"] == row["id"]

    def test_stats(self, rstore: RedisHitlStore):
        rstore.put(_sample(status="pending"))
        rstore.put(_sample(status="rejected"))
        st = rstore.stats()
        assert st["total"] >= 2
        assert st["pending"] >= 1
        assert st["rejected"] >= 1

    def test_list_source_filter(self, rstore: RedisHitlStore):
        rstore.put(_sample(source="rag", document_id="s1"))
        rstore.put(_sample(source="ingest", document_id="s1"))
        rows, total = rstore.list(document_id="s1", source="rag")
        assert total == 1
        assert rows[0]["source"] == "rag"

    def test_clear(self, rstore: RedisHitlStore):
        rstore.put(_sample())
        rstore.put(_sample())
        n = rstore.clear()
        assert n >= 2
        _, total = rstore.list()
        assert total == 0


# ---------------------------------------------------------------------------
# Cross-backend contract (memory always; redis optional)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["memory", pytest.param("redis", marks=requires_redis)])
def any_store(request):
    if request.param == "memory":
        store: Any = InMemoryHitlStore(max_items=100)
    else:
        store = RedisHitlStore()
        if not store.ping():
            pytest.skip("Redis not reachable")
        store.prefix = f"hitl:contract:{new_item_id()[:8]}"
    yield store
    if hasattr(store, "clear"):
        store.clear()


class TestStoreContract:
    def test_roundtrip(self, any_store: Any):
        row = any_store.put(_sample(document_id="contract-1"))
        got = any_store.get(row["id"])
        assert got is not None
        assert got["document_id"] == "contract-1"
        any_store.update(row["id"], status="modified", payload={"edited": True})
        got2 = any_store.get(row["id"])
        assert got2["status"] == "modified"
        assert got2["payload"]["edited"] is True
        rows, total = any_store.list(status="modified")
        assert total >= 1
        assert any_store.delete(row["id"]) is True
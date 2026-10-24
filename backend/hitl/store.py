"""
HITL queue persistence.

Backends
--------
- memory (default) — thread-safe in-process store
- redis            — shared queue across workers/instances

Env
---
HITL_STORE_BACKEND     memory | redis          (default: memory)
HITL_STORE_MAX_ITEMS   in-memory cap           (default: 5000)
HITL_REDIS_URL         redis://... or rediss://
HITL_REDIS_PREFIX      key prefix              (default: hitl:queue)
HITL_REDIS_TTL_SEC     item TTL seconds, 0=off (default: 0)
HITL_REDIS_SOCKET_TIMEOUT  seconds             (default: 5)

Redis requires: pip install redis
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from threading import Lock
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None  # type: ignore


class QueueStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    modified = "modified"
    skipped = "skipped"


_PRUNE_ORDER = (
    QueueStatus.skipped.value,
    QueueStatus.approved.value,
    QueueStatus.rejected.value,
    QueueStatus.modified.value,
)

_VALID_STATUS = frozenset(s.value for s in QueueStatus)


def new_item_id() -> str:
    return str(uuid.uuid4())


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Ensure required fields on every stored row."""
    out = dict(item)
    item_id = str(out.get("id") or new_item_id())
    now = time.time()
    out["id"] = item_id
    out.setdefault("created_at", now)
    out["updated_at"] = now
    status = str(out.get("status") or QueueStatus.pending.value).lower()
    if status not in _VALID_STATUS:
        status = QueueStatus.pending.value
    out["status"] = status
    return out


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class HitlStore(ABC):
    """Contract used by backend.hitl.service."""

    @abstractmethod
    def put(self, item: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def get(self, item_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def delete(self, item_id: str) -> bool:
        ...

    @abstractmethod
    def list(
        self,
        *,
        status: str | None = None,
        document_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ...

    @abstractmethod
    def update(self, item_id: str, **fields: Any) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def stats(self) -> dict[str, int]:
        ...

    def clear(self) -> int:
        rows, _ = self.list(limit=10_000, offset=0)
        n = 0
        for row in rows:
            rid = str(row.get("id") or "")
            if rid and self.delete(rid):
                n += 1
        return n

    def exists(self, item_id: str) -> bool:
        return self.get(item_id) is not None

    def get_many(self, item_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Fetch multiple items; skips missing ids."""
        out: list[dict[str, Any]] = []
        for iid in item_ids:
            row = self.get(str(iid))
            if row is not None:
                out.append(row)
        return out

    def delete_many(self, item_ids: Iterable[str]) -> int:
        n = 0
        for iid in item_ids:
            if self.delete(str(iid)):
                n += 1
        return n

    def count(
        self,
        *,
        status: str | None = None,
        document_id: str | None = None,
        source: str | None = None,
    ) -> int:
        _, total = self.list(
            status=status,
            document_id=document_id,
            source=source,
            limit=1,
            offset=0,
        )
        return total

    def claim_next_pending(
        self,
        *,
        reviewer_id: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Atomically-ish take the oldest pending item (best-effort on memory;
        Redis uses a short optimistic path). Marks status stays pending but
        sets claimed_by / claimed_at for UI locking.
        """
        rows, _ = self.list(status=QueueStatus.pending.value, source=source, limit=50, offset=0)
        # list is newest-first; claim oldest pending
        rows = list(reversed(rows))
        for row in rows:
            item_id = str(row["id"])
            if row.get("claimed_by") and row.get("claimed_at"):
                # still claimed within 15 minutes → skip
                try:
                    if time.time() - float(row["claimed_at"]) < 900:
                        continue
                except (TypeError, ValueError):
                    pass
            updated = self.update(
                item_id,
                claimed_by=reviewer_id or "anonymous",
                claimed_at=time.time(),
            )
            if updated is not None:
                return updated
        return None

    def health(self) -> dict[str, Any]:
        """Backend health snapshot for /ready or admin."""
        try:
            st = self.stats()
            return {
                "ok": True,
                "backend": type(self).__name__,
                "pending": int(st.get("pending", 0)),
                "total": int(st.get("total", 0)),
            }
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "backend": type(self).__name__, "error": str(exc)}


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class InMemoryHitlStore(HitlStore):
    """Process-local store — one API instance / tests."""

    def __init__(self, max_items: int | None = None) -> None:
        self._lock = Lock()
        self._items: dict[str, dict[str, Any]] = {}
        self._max_items = (
            max_items
            if max_items is not None
            else max(100, _env_int("HITL_STORE_MAX_ITEMS", 5000))
        )

    def put(self, item: dict[str, Any]) -> dict[str, Any]:
        item = _normalize_item(item)
        item_id = str(item["id"])
        with self._lock:
            self._items[item_id] = item
            self._prune_unlocked()
            return dict(self._items[item_id])

    def get(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._items.get(item_id)
            return dict(row) if row else None

    def delete(self, item_id: str) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None

    def update(self, item_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            row = self._items.get(item_id)
            if row is None:
                return None
            row = dict(row)
            fields.pop("id", None)
            if "status" in fields and fields["status"] is not None:
                st = str(fields["status"]).lower()
                fields["status"] = st if st in _VALID_STATUS else row.get("status")
            row.update(fields)
            row["updated_at"] = time.time()
            self._items[item_id] = row
            return dict(row)

    def list(
        self,
        *,
        status: str | None = None,
        document_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        with self._lock:
            rows = list(self._items.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if document_id:
            rows = [r for r in rows if r.get("document_id") == document_id]
        if source:
            rows = [r for r in rows if r.get("source") == source]
        rows.sort(key=lambda r: float(r.get("created_at") or 0.0), reverse=True)
        total = len(rows)
        return [dict(r) for r in rows[offset : offset + limit]], total

    def find(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(r) for r in self._items.values() if predicate(r)]
        rows.sort(key=lambda r: float(r.get("created_at") or 0.0), reverse=True)
        return rows[: max(1, min(limit, 1000))]

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = list(self._items.values())
        counts = {s.value: 0 for s in QueueStatus}
        for r in rows:
            key = str(r.get("status") or "")
            if key in counts:
                counts[key] += 1
        counts["total"] = len(rows)
        counts["max_items"] = self._max_items
        return counts

    def clear(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            return n

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def _prune_unlocked(self) -> int:
        overflow = len(self._items) - self._max_items
        if overflow <= 0:
            return 0
        removed = 0
        for st in _PRUNE_ORDER:
            if removed >= overflow:
                break
            candidates = [
                (str(i["id"]), float(i.get("created_at") or 0.0))
                for i in self._items.values()
                if i.get("status") == st
            ]
            candidates.sort(key=lambda t: t[1])
            for item_id, _ in candidates:
                if removed >= overflow:
                    break
                if item_id in self._items:
                    del self._items[item_id]
                    removed += 1
        if removed:
            logger.info(
                "HITL memory store pruned %s item(s) (max=%s)",
                removed,
                self._max_items,
            )
        return removed


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class RedisHitlStore(HitlStore):
    """
    Redis-backed store for multi-instance deployments.

    Keys:
      {prefix}:item:{id}     JSON item
      {prefix}:ids           ZSET score=created_at
      {prefix}:status:{st}   SET of ids
      {prefix}:doc:{doc_id}  SET of ids
      {prefix}:source:{src}  SET of ids
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        prefix: str | None = None,
        ttl_sec: int | None = None,
        client: Any | None = None,
    ) -> None:
        if redis_lib is None and client is None:
            raise RuntimeError("redis package not installed. pip install redis")

        self.prefix = (
            prefix or os.getenv("HITL_REDIS_PREFIX") or "hitl:queue"
        ).rstrip(":")
        self.ttl_sec = (
            ttl_sec
            if ttl_sec is not None
            else max(0, _env_int("HITL_REDIS_TTL_SEC", 0))
        )
        timeout = _env_float("HITL_REDIS_SOCKET_TIMEOUT", 5.0)
        self._r = client or redis_lib.Redis.from_url(
            url or os.getenv("HITL_REDIS_URL") or "redis://localhost:6379/0",
            decode_responses=True,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
        )

    def _item_key(self, item_id: str) -> str:
        return f"{self.prefix}:item:{item_id}"

    def _ids_key(self) -> str:
        return f"{self.prefix}:ids"

    def _status_key(self, status: str) -> str:
        return f"{self.prefix}:status:{status}"

    def _doc_key(self, document_id: str) -> str:
        return f"{self.prefix}:doc:{document_id}"

    def _source_key(self, source: str) -> str:
        return f"{self.prefix}:source:{source}"

    def _dumps(self, item: dict[str, Any]) -> str:
        return json.dumps(item, default=str)

    def _loads(self, raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            logger.warning("HITL Redis: corrupt JSON for an item key")
            return None

    def _index_add(self, pipe: Any, item: dict[str, Any]) -> None:
        item_id = str(item["id"])
        created = float(item.get("created_at") or time.time())
        status = str(item.get("status") or QueueStatus.pending.value)
        pipe.zadd(self._ids_key(), {item_id: created})
        pipe.sadd(self._status_key(status), item_id)
        doc = item.get("document_id")
        if doc:
            pipe.sadd(self._doc_key(str(doc)), item_id)
        src = item.get("source")
        if src:
            pipe.sadd(self._source_key(str(src)), item_id)

    def _index_remove(self, pipe: Any, item: dict[str, Any]) -> None:
        item_id = str(item["id"])
        status = str(item.get("status") or "")
        pipe.zrem(self._ids_key(), item_id)
        if status:
            pipe.srem(self._status_key(status), item_id)
        doc = item.get("document_id")
        if doc:
            pipe.srem(self._doc_key(str(doc)), item_id)
        src = item.get("source")
        if src:
            pipe.srem(self._source_key(str(src)), item_id)

    def _apply_ttl(self, pipe: Any, item_id: str) -> None:
        if self.ttl_sec > 0:
            pipe.expire(self._item_key(item_id), self.ttl_sec)

    def put(self, item: dict[str, Any]) -> dict[str, Any]:
        item = _normalize_item(item)
        item_id = str(item["id"])
        existing = self.get(item_id)
        pipe = self._r.pipeline()
        if existing:
            self._index_remove(pipe, existing)
        pipe.set(self._item_key(item_id), self._dumps(item))
        self._index_add(pipe, item)
        self._apply_ttl(pipe, item_id)
        pipe.execute()
        return dict(item)

    def get(self, item_id: str) -> dict[str, Any] | None:
        try:
            return self._loads(self._r.get(self._item_key(item_id)))
        except Exception as exc:
            logger.warning("HITL Redis get failed: %s", exc)
            return None

    def delete(self, item_id: str) -> bool:
        existing = self.get(item_id)
        if existing is None:
            return False
        pipe = self._r.pipeline()
        self._index_remove(pipe, existing)
        pipe.delete(self._item_key(item_id))
        pipe.execute()
        return True

    def update(self, item_id: str, **fields: Any) -> dict[str, Any] | None:
        current = self.get(item_id)
        if current is None:
            return None
        fields = dict(fields)
        fields.pop("id", None)
        if "status" in fields and fields["status"] is not None:
            st = str(fields["status"]).lower()
            fields["status"] = st if st in _VALID_STATUS else current.get("status")

        old_status = str(current.get("status") or "")
        old_doc = current.get("document_id")
        old_src = current.get("source")
        updated = dict(current)
        updated.update(fields)
        updated["updated_at"] = time.time()
        new_status = str(updated.get("status") or old_status)
        new_doc = updated.get("document_id")
        new_src = updated.get("source")

        pipe = self._r.pipeline()
        pipe.set(self._item_key(item_id), self._dumps(updated))
        self._apply_ttl(pipe, item_id)
        if old_status != new_status:
            if old_status:
                pipe.srem(self._status_key(old_status), item_id)
            pipe.sadd(self._status_key(new_status), item_id)
        if old_doc != new_doc:
            if old_doc:
                pipe.srem(self._doc_key(str(old_doc)), item_id)
            if new_doc:
                pipe.sadd(self._doc_key(str(new_doc)), item_id)
        if old_src != new_src:
            if old_src:
                pipe.srem(self._source_key(str(old_src)), item_id)
            if new_src:
                pipe.sadd(self._source_key(str(new_src)), item_id)
        pipe.zadd(
            self._ids_key(),
            {item_id: float(updated.get("created_at") or time.time())},
        )
        pipe.execute()
        return updated

    def list(
        self,
        *,
        status: str | None = None,
        document_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        keys: list[str] = []
        if status:
            keys.append(self._status_key(status))
        if document_id:
            keys.append(self._doc_key(document_id))
        if source:
            keys.append(self._source_key(source))

        try:
            if len(keys) >= 2:
                ids = list(self._r.sinter(*keys))
            elif len(keys) == 1:
                ids = list(self._r.smembers(keys[0]))
            else:
                ids = list(self._r.zrevrange(self._ids_key(), 0, -1))
        except Exception as exc:
            logger.warning("HITL Redis list index failed: %s", exc)
            ids = []

        rows: list[dict[str, Any]] = []
        for item_id in ids:
            row = self.get(str(item_id))
            if not row:
                continue
            # secondary filter if index was partial
            if status and row.get("status") != status:
                continue
            if document_id and row.get("document_id") != document_id:
                continue
            if source and row.get("source") != source:
                continue
            rows.append(row)

        rows.sort(key=lambda r: float(r.get("created_at") or 0.0), reverse=True)
        total = len(rows)
        return rows[offset : offset + limit], total

    def stats(self) -> dict[str, int]:
        counts = {s.value: 0 for s in QueueStatus}
        try:
            for st in QueueStatus:
                counts[st.value] = int(self._r.scard(self._status_key(st.value)))
            counts["total"] = int(self._r.zcard(self._ids_key()))
        except Exception as exc:
            logger.warning("HITL Redis stats failed: %s", exc)
            counts["total"] = 0
        return counts

    def clear(self) -> int:
        try:
            ids = list(self._r.zrange(self._ids_key(), 0, -1))
        except Exception:
            return 0
        n = 0
        for item_id in ids:
            if self.delete(str(item_id)):
                n += 1
        return n

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False

    def health(self) -> dict[str, Any]:
        base = super().health()
        base["redis_ping"] = self.ping()
        base["ok"] = bool(base.get("ok") and base["redis_ping"])
        base["prefix"] = self.prefix
        return base


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_store: HitlStore | None = None
_store_lock = Lock()


def create_hitl_store() -> HitlStore:
    """Build store from env (does not set singleton)."""
    backend = (os.getenv("HITL_STORE_BACKEND") or "memory").strip().lower()
    if backend in {"redis", "redis_store"}:
        if redis_lib is None:
            logger.warning(
                "HITL_STORE_BACKEND=redis but redis package missing; using memory"
            )
            return InMemoryHitlStore()
        try:
            store = RedisHitlStore()
            if hasattr(store, "ping") and not store.ping():
                logger.warning("Redis ping failed; using in-memory HITL store")
                return InMemoryHitlStore()
            logger.info("HITL store backend: redis")
            return store
        except Exception as exc:
            logger.warning("Redis HITL store init failed (%s); using memory", exc)
            return InMemoryHitlStore()

    logger.debug("HITL store backend: memory")
    return InMemoryHitlStore()


def get_hitl_store() -> HitlStore:
    """Singleton used by the service layer."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = create_hitl_store()
    return _store


def set_hitl_store(store: HitlStore) -> None:
    """Override singleton (tests / custom backends)."""
    global _store
    with _store_lock:
        _store = store


def reset_hitl_store() -> InMemoryHitlStore:
    """Fresh in-memory store for unit tests."""
    fresh = InMemoryHitlStore()
    set_hitl_store(fresh)
    return fresh


__all__ = [
    "QueueStatus",
    "HitlStore",
    "InMemoryHitlStore",
    "RedisHitlStore",
    "new_item_id",
    "create_hitl_store",
    "get_hitl_store",
    "set_hitl_store",
    "reset_hitl_store",
]
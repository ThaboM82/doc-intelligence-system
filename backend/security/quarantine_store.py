"""
Enterprise-Grade Persistent Quarantine Storage Engine.
Includes thread-safe file handling, automatic TTL expiration cleanup, audit telemetry hooks,
batch operations, compliance export/import, tenant isolation, and async wrappers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any, Callable

logger = logging.getLogger(__name__)

DATA_DIR = Path("backend/data")
QUARANTINE_FILE = DATA_DIR / "quarantine_store.json"


class QuarantineStore:
    def __init__(
        self,
        storage_path: Path | str = QUARANTINE_FILE,
        retention_days: int = 30,
        audit_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.retention_days = retention_days
        self.audit_callback = audit_callback
        self._lock = RLock()
        self._ensure_storage()
        self.purge_expired()  # Clean up expired items on startup

    def _ensure_storage(self) -> None:
        """Ensures storage directory and file exist with thread safety."""
        with self._lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                if not self.storage_path.exists():
                    self.storage_path.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.exception("Failed to initialize quarantine storage: %s", exc)

    def load(self) -> dict[str, Any]:
        """Loads all quarantined records thread-safely."""
        with self._lock:
            try:
                self._ensure_storage()
                content = self.storage_path.read_text(encoding="utf-8").strip()
                if not content:
                    return {}
                return json.loads(content)
            except Exception as exc:
                logger.exception("Failed to load quarantine store: %s", exc)
                return {}

    def save(self, data: dict[str, Any]) -> None:
        """Saves quarantined records thread-safely with sorted, formatted JSON."""
        with self._lock:
            try:
                self._ensure_storage()
                self.storage_path.write_text(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.exception("Failed to save quarantine store: %s", exc)

    def _trigger_audit(self, action: str, document_id: str, details: dict[str, Any]) -> None:
        """Triggers audit telemetry callback if configured."""
        if self.audit_callback:
            try:
                self.audit_callback(action, document_id, details)
            except Exception as exc:
                logger.debug("Audit callback failed: %s", exc)

    def add(self, document_id: str, item: dict[str, Any]) -> None:
        """Adds or updates a quarantined document record with timestamp and risk tier."""
        with self._lock:
            data = self.load()
            if "quarantined_at" not in item:
                item["quarantined_at"] = time.time()
            
            # Assign risk tier automatically if missing
            risk = item.get("risk_score", 0.0)
            if "risk_tier" not in item:
                item["risk_tier"] = (
                    "Critical" if risk >= 0.80 else
                    "High" if risk >= 0.60 else
                    "Medium" if risk >= 0.40 else "Low"
                )

            data[document_id] = item
            self.save(data)
            self._trigger_audit("QUARANTINE_ADDED", document_id, item)

    def get(self, document_id: str) -> dict[str, Any] | None:
        """Retrieves a specific quarantined document by ID."""
        data = self.load()
        return data.get(document_id)

    def delete(self, document_id: str) -> bool:
        """Deletes a quarantined record. Returns True if found and removed."""
        with self._lock:
            data = self.load()
            if document_id not in data:
                return False
            item = data.pop(document_id)
            self.save(data)
            self._trigger_audit("QUARANTINE_DELETED", document_id, item)
            return True

    def batch_delete(self, document_ids: list[str]) -> int:
        """Deletes multiple quarantined items in a single atomic transaction."""
        with self._lock:
            data = self.load()
            removed_count = 0
            for doc_id in document_ids:
                if doc_id in data:
                    data.pop(doc_id)
                    removed_count += 1
                    self._trigger_audit("QUARANTINE_BATCH_DELETED", doc_id, {})
            if removed_count > 0:
                self.save(data)
            return removed_count

    def purge_expired(self) -> int:
        """Purges quarantined items older than the retention period. Returns count purged."""
        if self.retention_days <= 0:
            return 0

        with self._lock:
            data = self.load()
            now = time.time()
            cutoff = now - (self.retention_days * 86400)
            expired_ids = [
                doc_id for doc_id, item in data.items()
                if item.get("quarantined_at", 0.0) < cutoff
            ]

            if not expired_ids:
                return 0

            for doc_id in expired_ids:
                data.pop(doc_id)
                self._trigger_audit("QUARANTINE_EXPIRED_PURGE", doc_id, {})

            self.save(data)
            logger.info("Purged %d expired quarantined documents", len(expired_ids))
            return len(expired_ids)

    def list_all(self) -> dict[str, Any]:
        """Returns all quarantined records."""
        return self.load()

    def list_paginated(
        self,
        tenant_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
        min_risk_score: float | None = None,
        risk_tier: str | None = None,
    ) -> list[dict[str, Any]]:
        """Returns paginated and filtered quarantined items."""
        data = self.load()
        items = list(data.values())

        if tenant_id:
            items = [i for i in items if i.get("tenant_id") == tenant_id]

        if min_risk_score is not None:
            items = [i for i in items if i.get("risk_score", 0.0) >= min_risk_score]

        if risk_tier:
            items = [i for i in items if i.get("risk_tier", "").lower() == risk_tier.lower()]

        items.sort(key=lambda x: x.get("quarantined_at", 0.0), reverse=True)
        return items[skip : skip + limit]

    def get_stats(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Computes summary threat metrics for quarantined documents."""
        data = self.load()
        items = list(data.values())

        if tenant_id:
            items = [i for i in items if i.get("tenant_id") == tenant_id]

        total = len(items)
        if total == 0:
            return {
                "total_quarantined": 0,
                "average_risk_score": 0.0,
                "tenants_affected": 0,
                "risk_tier_breakdown": {"Low": 0, "Medium": 0, "High": 0, "Critical": 0},
            }

        avg_risk = sum(i.get("risk_score", 0.0) for i in items) / total
        unique_tenants = len(set(i.get("tenant_id") for i in items if i.get("tenant_id")))
        
        breakdown = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
        for i in items:
            tier = i.get("risk_tier", "Low")
            if tier in breakdown:
                breakdown[tier] += 1

        return {
            "total_quarantined": total,
            "average_risk_score": round(avg_risk, 4),
            "tenants_affected": unique_tenants,
            "risk_tier_breakdown": breakdown,
        }

    def export_snapshot(self) -> str:
        """Exports quarantine data as a JSON string for compliance backups."""
        return json.dumps(self.load(), indent=2, ensure_ascii=False)

    def import_snapshot(self, json_data: str, overwrite: bool = False) -> int:
        """Imports a JSON quarantine snapshot. Returns number of items imported."""
        try:
            incoming = json.loads(json_data)
            if not isinstance(incoming, dict):
                raise ValueError("Snapshot must be a JSON dictionary mapping document IDs to records.")
            
            with self._lock:
                current = {} if overwrite else self.load()
                current.update(incoming)
                self.save(current)
                return len(incoming)
        except Exception as exc:
            logger.exception("Failed to import quarantine snapshot: %s", exc)
            raise

    def clear(self) -> None:
        """Clears all quarantine records."""
        with self._lock:
            self.save({})
            self._trigger_audit("QUARANTINE_STORE_CLEARED", "ALL", {})

    # ---------------------------------------------------------------------------
    # Asynchronous Wrappers (for FastAPI async route handlers)
    # ---------------------------------------------------------------------------

    async def aload(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.load)

    async def asave(self, data: dict[str, Any]) -> None:
        await asyncio.to_thread(self.save, data)

    async def aadd(self, document_id: str, item: dict[str, Any]) -> None:
        await asyncio.to_thread(self.add, document_id, item)

    async def aget(self, document_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.get, document_id)

    async def adelete(self, document_id: str) -> bool:
        return await asyncio.to_thread(self.delete, document_id)

    async def abatch_delete(self, document_ids: list[str]) -> int:
        return await asyncio.to_thread(self.batch_delete, document_ids)

    async def alist_paginated(
        self,
        tenant_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
        min_risk_score: float | None = None,
        risk_tier: str | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.list_paginated, tenant_id, skip, limit, min_risk_score, risk_tier
        )


quarantine_store = QuarantineStore()
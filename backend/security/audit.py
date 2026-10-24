"""
Enterprise Security Audit Trail

Tracks:
- Document uploads
- Document deletions
- Security scans
- Prompt injection attempts
- DLP detections
- Secret exposures
- Quarantine actions
- Email header verification
- Policy updates
- Authentication activity
- Administrative actions
- Security alerts
- RAG activity

Storage:
- JSON file persistence

Future:
- PostgreSQL
- Qdrant
- SIEM integration
- ElasticSearch
- Microsoft Sentinel
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# Centralized observability metrics integration
try:
    from backend.observability.metrics import metrics_collector
except ImportError:
    metrics_collector = None  # Graceful fallback for isolated test environments

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
AUDIT_FILE = DATA_DIR / "security_audit.json"


# ============================================================================
# Severities
# ============================================================================

SEVERITY_INFO = "info"
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"


# ============================================================================
# Event Types
# ============================================================================

EVENT_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
EVENT_DOCUMENT_INDEXED = "DOCUMENT_INDEXED"
EVENT_DOCUMENT_DELETED = "DOCUMENT_DELETED"

EVENT_SCAN_STARTED = "SCAN_STARTED"
EVENT_SCAN_COMPLETED = "SCAN_COMPLETED"
EVENT_SCAN_FAILED = "SCAN_FAILED"

EVENT_PROMPT_INJECTION = "PROMPT_INJECTION"

EVENT_DLP_DETECTED = "DLP_DETECTED"

EVENT_SECRET_EXPOSURE = "SECRET_EXPOSURE"

EVENT_DOCUMENT_QUARANTINED = "DOCUMENT_QUARANTINED"
EVENT_DOCUMENT_RELEASED = "DOCUMENT_RELEASED"

EVENT_POLICY_UPDATED = "POLICY_UPDATED"

EVENT_HEADER_VERIFICATION = "HEADER_VERIFICATION"

EVENT_LOGIN_SUCCESS = "LOGIN_SUCCESS"
EVENT_LOGIN_FAILURE = "LOGIN_FAILURE"

EVENT_ADMIN_ACTION = "ADMIN_ACTION"

EVENT_SECURITY_ALERT = "SECURITY_ALERT"

EVENT_RAG_QUERY = "RAG_QUERY"

EVENT_TENANT_CREATED = "TENANT_CREATED"
EVENT_TENANT_UPDATED = "TENANT_UPDATED"


# ============================================================================
# Models
# ============================================================================

@dataclass
class SecurityEvent:
    event_id: str
    tenant_id: str
    action: str
    severity: str
    timestamp: str

    document_id: str | None = None
    user_id: str | None = None
    username: str | None = None
    source_ip: str | None = None

    metadata: dict[str, Any] | None = None


# ============================================================================
# Repository
# ============================================================================

class SecurityAuditRepository:
    def __init__(self) -> None:
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not AUDIT_FILE.exists():
            AUDIT_FILE.write_text(
                "[]",
                encoding="utf-8",
            )

    def _read_events(self) -> list[dict]:
        try:
            self._ensure_storage()

            content = AUDIT_FILE.read_text(
                encoding="utf-8"
            ).strip()

            if not content:
                return []

            return json.loads(content)

        except Exception as exc:
            logger.exception(
                "Failed to read audit file: %s",
                exc,
            )
            return []

    def _write_events(
        self,
        events: list[dict],
    ) -> None:
        try:
            self._ensure_storage()

            AUDIT_FILE.write_text(
                json.dumps(
                    events,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        except Exception as exc:
            logger.exception(
                "Failed to write audit file: %s",
                exc,
            )

    def add_event(
        self,
        event: SecurityEvent,
    ) -> None:
        events = self._read_events()

        events.append(
            asdict(event)
        )

        self._write_events(events)

    def get_event(
        self,
        event_id: str,
    ) -> dict[str, Any] | None:

        for event in self._read_events():
            if event.get("event_id") == event_id:
                return event

        return None

    def list_events(
        self,
        tenant_id: str | None = None,
    ) -> list[dict]:

        events = self._read_events()

        if tenant_id:
            return [
                event
                for event in events
                if event.get("tenant_id") == tenant_id
            ]

        return events

    def recent(
        self,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> list[dict]:
        events = self.list_events(
            tenant_id=tenant_id
        )

        events.sort(
            key=lambda x: x.get(
                "timestamp",
                "",
            )
        )

        return events[-limit:]

    def count_by_action(
        self,
        action: str,
        tenant_id: str | None = None,
    ) -> int:

        return len(
            [
                event
                for event in self.list_events(
                    tenant_id=tenant_id
                )
                if event.get("action") == action
            ]
        )

    def count_by_severity(
        self,
        severity: str,
        tenant_id: str | None = None,
    ) -> int:

        return len(
            [
                event
                for event in self.list_events(
                    tenant_id=tenant_id
                )
                if event.get("severity") == severity
            ]
        )

    def search(
        self,
        tenant_id: str,
        action: str | None = None,
        severity: str | None = None,
    ) -> list[dict]:
        events = self.list_events(
            tenant_id=tenant_id
        )

        if action:
            events = [
                e
                for e in events
                if e.get("action") == action
            ]

        if severity:
            events = [
                e
                for e in events
                if e.get("severity") == severity
            ]

        return events

    def purge_old_events(
        self,
        retention_days: int = 365,
    ) -> int:

        cutoff = datetime.now(
            timezone.utc
        ) - timedelta(days=retention_days)

        retained = []
        removed = 0

        for event in self._read_events():

            timestamp = event.get(
                "timestamp"
            )

            if not timestamp:
                continue

            ts = datetime.fromisoformat(
                timestamp
            )

            if ts < cutoff:
                removed += 1
            else:
                retained.append(
                    event
                )

        self._write_events(
            retained
        )

        return removed


# ============================================================================
# Singleton Repository
# ============================================================================

audit_repo = SecurityAuditRepository()


# ============================================================================
# Public Helpers
# ============================================================================

def record_security_event(
    tenant_id: str,
    action: str,
    severity: str = SEVERITY_LOW,
    *,
    document_id: str | None = None,
    user_id: str | None = None,
    username: str | None = None,
    source_ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:

    event = SecurityEvent(
        event_id=str(uuid4()),
        tenant_id=tenant_id,
        action=action,
        severity=severity,
        timestamp=datetime.now(
            timezone.utc
        ).isoformat(),
        document_id=document_id,
        user_id=user_id,
        username=username,
        source_ip=source_ip,
        metadata=metadata or {},
    )

    audit_repo.add_event(event)

    # Increment observability metrics if collector is available
    if metrics_collector:
        if action == EVENT_LOGIN_FAILURE:
            metrics_collector.increment("security.auth.failures")
        elif action == EVENT_LOGIN_SUCCESS:
            metrics_collector.increment("security.auth.success")
        elif action == EVENT_PROMPT_INJECTION:
            metrics_collector.increment("security.threats.prompt_injections")
        elif action in (EVENT_DLP_DETECTED, EVENT_SECRET_EXPOSURE):
            metrics_collector.increment("security.dlp.violations")
        elif action == EVENT_DOCUMENT_QUARANTINED:
            metrics_collector.increment("security.quarantine.added")

    return event.event_id


def get_tenant_events(
    tenant_id: str,
) -> list[SecurityEvent]:
    return audit_repo.list_events(
        tenant_id=tenant_id
    )


def get_recent_events(
    tenant_id: str,
    limit: int = 50,
) -> list[SecurityEvent]:
    return audit_repo.recent(
        limit=limit,
        tenant_id=tenant_id,
    )


def search_events(
    tenant_id: str,
    action: str | None = None,
    severity: str | None = None,
) -> list[SecurityEvent]:
    return audit_repo.search(
        tenant_id=tenant_id,
        action=action,
        severity=severity,
    )


def export_events(
    tenant_id: str | None = None,
) -> list[SecurityEvent]:
    return audit_repo.list_events(
        tenant_id=tenant_id
    )


def purge_old_events(
    retention_days: int = 365,
) -> int:

    return audit_repo.purge_old_events(
        retention_days
    )


def dashboard_summary(
    tenant_id: str,
) -> dict[str, Any]:

    events = audit_repo.list_events(
        tenant_id=tenant_id
    )

    return {
        "total_events": len(events),
        "critical_events": audit_repo.count_by_severity(
            SEVERITY_CRITICAL,
            tenant_id=tenant_id,
        ),
        "high_events": audit_repo.count_by_severity(
            SEVERITY_HIGH,
            tenant_id=tenant_id,
        ),
        "medium_events": audit_repo.count_by_severity(
            SEVERITY_MEDIUM,
            tenant_id=tenant_id,
        ),
        "quarantined_documents": audit_repo.count_by_action(
            EVENT_DOCUMENT_QUARANTINED,
            tenant_id=tenant_id,
        ),
        "prompt_injections": audit_repo.count_by_action(
            EVENT_PROMPT_INJECTION,
            tenant_id=tenant_id,
        ),
        "secret_exposures": audit_repo.count_by_action(
            EVENT_SECRET_EXPOSURE,
            tenant_id=tenant_id,
        ),
        "dlp_detections": audit_repo.count_by_action(
            EVENT_DLP_DETECTED,
            tenant_id=tenant_id,
        ),
        "rag_queries": audit_repo.count_by_action(
            EVENT_RAG_QUERY,
            tenant_id=tenant_id,
        ),
    }
"""
tests/test_audit.py

Comprehensive Unit Test Suite for Enterprise Security Audit Trail.
Tests event recording, repository storage, retrieval limits, action/severity counts,
searching, and TTL retention purging.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from backend.security.audit import (
    SecurityAuditRepository,
    SecurityEvent,
    record_security_event,
    dashboard_summary,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGIN_FAILURE,
    EVENT_PROMPT_INJECTION,
    EVENT_DOCUMENT_QUARANTINED,
)


@pytest.fixture
def temp_audit_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SecurityAuditRepository:
    """Provides a SecurityAuditRepository instance bound to a temporary storage path."""
    test_audit_file = tmp_path / "security_audit.json"
    monkeypatch.setattr("backend.security.audit.AUDIT_FILE", test_audit_file)
    monkeypatch.setattr("backend.security.audit.DATA_DIR", tmp_path)
    return SecurityAuditRepository()


def test_record_and_get_event(temp_audit_repo: SecurityAuditRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test recording a security event and retrieving it by ID."""
    monkeypatch.setattr("backend.security.audit.audit_repo", temp_audit_repo)

    event_id = record_security_event(
        tenant_id="tenant_alpha",
        action=EVENT_LOGIN_SUCCESS,
        severity=SEVERITY_LOW,
        user_id="usr_123",
        username="alice",
        source_ip="192.168.1.50",
        metadata={"method": "oauth"},
    )

    assert isinstance(event_id, str)
    assert len(event_id) > 0

    retrieved = temp_audit_repo.get_event(event_id)
    assert retrieved is not None
    assert retrieved["event_id"] == event_id
    assert retrieved["tenant_id"] == "tenant_alpha"
    assert retrieved["action"] == EVENT_LOGIN_SUCCESS
    assert retrieved["severity"] == SEVERITY_LOW
    assert retrieved["username"] == "alice"
    assert retrieved["source_ip"] == "192.168.1.50"
    assert retrieved["metadata"]["method"] == "oauth"


def test_list_and_recent_events(temp_audit_repo: SecurityAuditRepository) -> None:
    """Test listing events by tenant and fetching recent event limits."""
    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="e1",
            tenant_id="t1",
            action=EVENT_LOGIN_FAILURE,
            severity=SEVERITY_HIGH,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="e2",
            tenant_id="t1",
            action=EVENT_PROMPT_INJECTION,
            severity=SEVERITY_CRITICAL,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="e3",
            tenant_id="t2",
            action=EVENT_LOGIN_SUCCESS,
            severity=SEVERITY_LOW,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    t1_events = temp_audit_repo.list_events(tenant_id="t1")
    assert len(t1_events) == 2

    all_events = temp_audit_repo.list_events()
    assert len(all_events) == 3

    recent = temp_audit_repo.recent(limit=2, tenant_id="t1")
    assert len(recent) == 2


def test_counts_and_search(temp_audit_repo: SecurityAuditRepository) -> None:
    """Test counting by action and severity, and searching events."""
    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="s1",
            tenant_id="alpha",
            action=EVENT_DOCUMENT_QUARANTINED,
            severity=SEVERITY_HIGH,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="s2",
            tenant_id="alpha",
            action=EVENT_PROMPT_INJECTION,
            severity=SEVERITY_CRITICAL,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    assert temp_audit_repo.count_by_action(EVENT_PROMPT_INJECTION, tenant_id="alpha") == 1
    assert temp_audit_repo.count_by_severity(SEVERITY_CRITICAL, tenant_id="alpha") == 1

    search_results = temp_audit_repo.search(tenant_id="alpha", severity=SEVERITY_HIGH)
    assert len(search_results) == 1
    assert search_results[0]["event_id"] == "s1"


def test_purge_old_events(temp_audit_repo: SecurityAuditRepository) -> None:
    """Test purging events older than retention days."""
    old_time = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    recent_time = datetime.now(timezone.utc).isoformat()

    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="old_event",
            tenant_id="t1",
            action=EVENT_LOGIN_SUCCESS,
            severity=SEVERITY_LOW,
            timestamp=old_time,
        )
    )
    temp_audit_repo.add_event(
        SecurityEvent(
            event_id="recent_event",
            tenant_id="t1",
            action=EVENT_LOGIN_SUCCESS,
            severity=SEVERITY_LOW,
            timestamp=recent_time,
        )
    )

    assert len(temp_audit_repo.list_events()) == 2

    removed = temp_audit_repo.purge_old_events(retention_days=365)
    assert removed == 1

    remaining = temp_audit_repo.list_events()
    assert len(remaining) == 1
    assert remaining[0]["event_id"] == "recent_event"


def test_dashboard_summary(temp_audit_repo: SecurityAuditRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test summary statistics generation for dashboard views."""
    monkeypatch.setattr("backend.security.audit.audit_repo", temp_audit_repo)

    record_security_event("t_dash", EVENT_PROMPT_INJECTION, SEVERITY_CRITICAL)
    record_security_event("t_dash", EVENT_DOCUMENT_QUARANTINED, SEVERITY_HIGH)

    summary = dashboard_summary("t_dash")
    assert summary["total_events"] == 2
    assert summary["critical_events"] == 1
    assert summary["high_events"] == 1
    assert summary["quarantined_documents"] == 1
    assert summary["prompt_injections"] == 1
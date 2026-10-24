"""
tests/test_hitl_reviewer.py

Unit tests for backend.hitl.reviewer — Human-in-the-Loop routing heuristics.

Covers:
  * Pass path (high confidence, clean text)
  * Rule 1 low confidence + exact threshold boundary
  * Rule 2 high/critical risk tiers (case-insensitive)
  * Rule 3 missing required extraction fields
  * Policy keywords and PII/secret regex detectors
  * Metrics hook invocation
  * Env overrides: HITL_CONFIDENCE_THRESHOLD, HITL_ENABLED, HITL_FORCE_REVIEW
  * evaluate_for_review_detailed / collect_all / should_queue_for_human
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

from backend.hitl import reviewer
from backend.hitl.reviewer import (
    CONFIDENCE_THRESHOLD,
    HitlDecision,
    evaluate_for_review,
    evaluate_for_review_detailed,
    should_queue_for_human,
)


# ---------------------------------------------------------------------------
# Pass path
# ---------------------------------------------------------------------------


def test_passed_verification():
    """Clean extraction with high confidence passes without review."""
    extracted = {"id": "123", "name": "Secure Report"}
    needs_review, reason = evaluate_for_review(
        confidence_score=0.95,
        extracted_data=extracted,
        risk_level="low",
        text_content="Standard enterprise operations document.",
    )
    assert needs_review is False
    assert "Passed automated verification" in reason


def test_passed_verification_detailed():
    """Detailed API returns HitlDecision with empty triggers on pass."""
    decision = evaluate_for_review_detailed(
        confidence_score=0.99,
        extracted_data={"id": "1", "title": "OK"},
        risk_level="low",
        text_content="Routine quarterly summary.",
        source="test",
        document_id="doc-1",
    )
    assert isinstance(decision, HitlDecision)
    assert decision.needs_review is False
    assert decision.triggers == []
    assert decision.severity == "none"
    assert decision.metadata.get("document_id") == "doc-1"


# ---------------------------------------------------------------------------
# Rule 1 — confidence
# ---------------------------------------------------------------------------


def test_rule_low_confidence():
    """Scores below threshold trigger review."""
    needs_review, reason = evaluate_for_review(
        confidence_score=CONFIDENCE_THRESHOLD - 0.05,
        extracted_data={"id": "123"},
        risk_level="low",
        text_content="Normal text.",
    )
    assert needs_review is True
    assert "Confidence score" in reason


def test_rule_confidence_boundary():
    """Exact threshold value should pass Rule 1 (comparison is strict <)."""
    needs_review, _ = evaluate_for_review(
        confidence_score=CONFIDENCE_THRESHOLD,
        extracted_data={"id": "123"},
        risk_level="low",
        text_content="Normal text.",
    )
    assert needs_review is False


def test_rule_confidence_invalid_treated_as_zero():
    """Non-numeric confidence is treated as 0.0 → review."""
    needs_review, reason = evaluate_for_review(
        confidence_score="not-a-number",  # type: ignore[arg-type]
        extracted_data={},
        risk_level="low",
        text_content="x",
    )
    assert needs_review is True
    assert "Confidence score" in reason


# ---------------------------------------------------------------------------
# Rule 2 — risk tier
# ---------------------------------------------------------------------------


def test_rule_high_risk_tier():
    """High or critical risk levels trigger review (case-insensitive)."""
    for risk in ["high", "CRITICAL", "High"]:
        needs_review, reason = evaluate_for_review(
            confidence_score=0.90,
            extracted_data={"id": "123"},
            risk_level=risk,
            text_content="Normal text.",
        )
        assert needs_review is True, f"expected review for risk={risk}"
        assert "risk level" in reason.lower()


def test_rule_medium_risk_does_not_force():
    """Medium risk alone does not force HITL when confidence is high."""
    needs_review, _ = evaluate_for_review(
        confidence_score=0.95,
        extracted_data={"id": "123"},
        risk_level="medium",
        text_content="Benign operational note.",
    )
    assert needs_review is False


# ---------------------------------------------------------------------------
# Rule 3 — required fields
# ---------------------------------------------------------------------------


def test_rule_missing_required_fields():
    """Missing mandatory extraction keys trigger review."""
    extracted = {
        "required_keys": ["invoice_number", "total_amount"],
        "invoice_number": "INV-2026-001",
        "total_amount": None,
    }
    needs_review, reason = evaluate_for_review(
        confidence_score=0.90,
        extracted_data=extracted,
        risk_level="low",
        text_content="Invoice details attached.",
    )
    assert needs_review is True
    assert "Mandatory extraction field" in reason
    assert "total_amount" in reason


def test_rule_required_fields_alias():
    """required_fields is accepted as an alias of required_keys."""
    extracted = {
        "required_fields": ["title"],
        "title": "",
    }
    needs_review, reason = evaluate_for_review(
        confidence_score=0.90,
        extracted_data=extracted,
        risk_level="low",
        text_content="Body only.",
    )
    assert needs_review is True
    assert "title" in reason


# ---------------------------------------------------------------------------
# Policy keywords & secrets / PII
# ---------------------------------------------------------------------------


def test_rule_policy_keywords():
    """Sensitive threat/policy keywords trigger review."""
    needs_review, reason = evaluate_for_review(
        confidence_score=0.90,
        extracted_data={"id": "123"},
        risk_level="low",
        text_content="Warning: Detected a phishing attempt and data_exfiltration vector.",
    )
    assert needs_review is True
    assert "sensitive policy/threat indicators" in reason.lower() or "phishing" in reason.lower()


def test_rule_api_key_secret_detection():
    """OpenAI-style secret patterns trigger review."""
    needs_review, reason = evaluate_for_review(
        confidence_score=0.90,
        extracted_data={"id": "123"},
        risk_level="low",
        text_content="mock-sk-abcdefghijklmnopqrstuvwxyz123456",
    )

    assert needs_review is True
    # Expanded reviewer uses "sensitive patterns"; older wording also accepted
    assert (
        "sensitive" in reason.lower()
        or "pii" in reason.lower()
        or "secret" in reason.lower()
        or "sk-" in reason.lower()
        or "openai" in reason.lower()
        or "pattern" in reason.lower()
    )


def test_rule_credit_card_detection():
    """Credit-card-like digit groups trigger review."""
    needs_review, reason = evaluate_for_review(
        confidence_score=0.90,
        extracted_data={"id": "123"},
        risk_level="low",
        text_content="Customer payment card on file: 4532 1234 5678 9010",
    )
    assert needs_review is True
    assert "sensitive" in reason.lower() or "pattern" in reason.lower() or "pii" in reason.lower()


def test_rule_private_key_block():
    """PEM private key headers are treated as critical-sensitive."""
    decision = evaluate_for_review_detailed(
        confidence_score=0.99,
        extracted_data={},
        risk_level="low",
        text_content="-----BEGIN RSA PRIVATE KEY-----\nMIIE...",
        collect_all=True,
    )
    assert decision.needs_review is True
    assert "pii_or_secret_detected" in decision.triggers


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@patch("backend.hitl.reviewer.record_hitl_trigger")
def test_metrics_recording_called(mock_record_metric):
    """Prometheus/metrics helper is invoked when HITL fires."""
    evaluate_for_review(
        confidence_score=0.50,
        extracted_data={"id": "123"},
        risk_level="low",
        text_content="Normal text.",
    )
    mock_record_metric.assert_called_once_with("low_confidence")


# ---------------------------------------------------------------------------
# Environment switches
# ---------------------------------------------------------------------------


def test_environment_threshold_override():
    """HITL_CONFIDENCE_THRESHOLD env var is applied on module reload."""
    with patch.dict(os.environ, {"HITL_CONFIDENCE_THRESHOLD": "0.55"}):
        importlib.reload(reviewer)
        assert reviewer.CONFIDENCE_THRESHOLD == pytest.approx(0.55)
    importlib.reload(reviewer)


def test_hitl_disabled_skips_all_rules():
    """When HITL_ENABLED=false, even low confidence passes."""
    with patch.dict(os.environ, {"HITL_ENABLED": "false", "HITL_FORCE_REVIEW": "false"}):
        importlib.reload(reviewer)
        needs, reason = reviewer.evaluate_for_review(
            confidence_score=0.1,
            extracted_data={},
            risk_level="critical",
            text_content="phishing sk-abcdefghijklmnopqrstuvwxyz123456",
        )
        assert needs is False
        assert "disabled" in reason.lower()
    importlib.reload(reviewer)


def test_hitl_force_review():
    """HITL_FORCE_REVIEW routes everything to humans."""
    with patch.dict(os.environ, {"HITL_FORCE_REVIEW": "true", "HITL_ENABLED": "true"}):
        importlib.reload(reviewer)
        needs, reason = reviewer.evaluate_for_review(
            confidence_score=0.99,
            extracted_data={"id": "1"},
            risk_level="low",
            text_content="Perfectly clean text.",
        )
        assert needs is True
        assert "FORCE" in reason.upper() or "force" in reason.lower()
    importlib.reload(reviewer)


# ---------------------------------------------------------------------------
# collect_all + helpers
# ---------------------------------------------------------------------------


def test_collect_all_aggregates_triggers():
    """collect_all=True can surface multiple trigger categories."""
    decision = evaluate_for_review_detailed(
        confidence_score=0.2,
        extracted_data={"required_keys": ["title"], "title": None},
        risk_level="critical",
        text_content="phishing campaign detected",
        collect_all=True,
    )
    assert decision.needs_review is True
    assert len(decision.triggers) >= 2
    assert decision.severity in {"high", "critical"}


def test_should_queue_for_human_tuple_and_decision():
    assert should_queue_for_human((True, "x")) is True
    assert should_queue_for_human((False, "ok")) is False
    assert should_queue_for_human(HitlDecision(True, "review")) is True
    assert should_queue_for_human(HitlDecision(False, "ok")) is False


def test_decision_to_dict_and_as_tuple():
    d = HitlDecision(
        needs_review=True,
        reason="test",
        triggers=["low_confidence"],
        severity="medium",
        confidence_score=0.4,
    )
    assert d.as_tuple() == (True, "test")
    payload = d.to_dict()
    assert payload["needs_review"] is True
    assert payload["triggers"] == ["low_confidence"]
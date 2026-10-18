"""
Reviewer heuristic engine for Human-in-the-Loop (HITL) routing.

Evaluates extraction confidence, risk levels, policy triggers, threat indicators,
and PII/sensitive data exposure to decide if an automated result requires human
expert sign-off.

Env:
  HITL_CONFIDENCE_THRESHOLD   default 0.75
  HITL_ENABLED                default true
  HITL_FORCE_REVIEW           if true, always route to human
  HITL_MAX_TEXT_SCAN_CHARS    default 200000 (cap scan cost)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    from backend.observability.metrics import record_hitl_trigger
except ImportError:  # pragma: no cover

    def record_hitl_trigger(category: str) -> None:
        pass


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


HITL_ENABLED = _env_bool("HITL_ENABLED", True)
HITL_FORCE_REVIEW = _env_bool("HITL_FORCE_REVIEW", False)
CONFIDENCE_THRESHOLD = _env_float("HITL_CONFIDENCE_THRESHOLD", 0.75)
MAX_TEXT_SCAN_CHARS = int(os.getenv("HITL_MAX_TEXT_SCAN_CHARS", "200000"))

SENSITIVE_POLICY_KEYWORDS = frozenset(
    {
        "malicious",
        "phishing",
        "unauthorized",
        "credential harvesting",
        "credential_harvesting",
        "critical vulnerability",
        "critical_vulnerability",
        "data exfiltration",
        "data_exfiltration",
        "bypass",
        "exploit",
        "ransomware",
        "privilege escalation",
        "zero-day",
        "backdoor",
    }
)

# High-signal patterns (keep conservative to limit false positives)
SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("credit_card_like", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("openai_sk_key", re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic_bearer", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    (
        "email_address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "ssn_like",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    ),
]

# Categories that force review even at high confidence
FORCE_RISK_LEVELS = frozenset({"high", "critical"})


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class HitlDecision:
    """Structured HITL routing decision."""

    needs_review: bool
    reason: str
    triggers: list[str] = field(default_factory=list)
    severity: str = "none"  # none | low | medium | high | critical
    confidence_score: float = 0.0
    risk_level: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_tuple(self) -> tuple[bool, str]:
        """Backward-compatible (needs_review, reason)."""
        return self.needs_review, self.reason

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _severity_rank(level: str) -> int:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    return order.get((level or "none").lower(), 0)


def _bump_severity(current: str, new: str) -> str:
    return new if _severity_rank(new) > _severity_rank(current) else current


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------


def _scan_keywords(text: str) -> list[str]:
    lower = text.lower()
    return sorted(kw for kw in SENSITIVE_POLICY_KEYWORDS if kw in lower)


def _scan_patterns(text: str) -> list[str]:
    hits: list[str] = []
    for name, pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            hits.append(name)
    return hits


def _missing_required_fields(extracted_data: dict[str, Any]) -> list[str]:
    required = extracted_data.get("required_keys") or extracted_data.get("required_fields") or []
    if not isinstance(required, (list, tuple, set)):
        return []
    missing: list[str] = []
    for key in required:
        if not key:
            continue
        val = extracted_data.get(str(key))
        if val is None or val == "" or val == [] or val == {}:
            missing.append(str(key))
    return missing


def _anomalous_extraction(extracted_data: dict[str, Any]) -> list[str]:
    """Light anomaly signals without domain-specific schemas."""
    flags: list[str] = []
    if not extracted_data:
        return flags

    # Extremely long free-text fields can indicate dump / injection
    for key, val in extracted_data.items():
        if key in {"required_keys", "required_fields", "metadata"}:
            continue
        if isinstance(val, str) and len(val) > 50_000:
            flags.append(f"oversized_field:{key}")
    return flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_for_review(
    confidence_score: float,
    extracted_data: dict[str, Any] | None = None,
    risk_level: str = "low",
    text_content: str = "",
    *,
    source: str | None = None,
    document_id: str | None = None,
    collect_all: bool = False,
) -> tuple[bool, str]:
    """
    Decide whether automated output needs human review.

    Returns:
        (needs_review, reason) — same contract as before.

    For full detail, use evaluate_for_review_detailed().
    """
    decision = evaluate_for_review_detailed(
        confidence_score=confidence_score,
        extracted_data=extracted_data,
        risk_level=risk_level,
        text_content=text_content,
        source=source,
        document_id=document_id,
        collect_all=collect_all,
    )
    return decision.as_tuple()


def evaluate_for_review_detailed(
    confidence_score: float,
    extracted_data: dict[str, Any] | None = None,
    risk_level: str = "low",
    text_content: str = "",
    *,
    source: str | None = None,
    document_id: str | None = None,
    collect_all: bool = False,
) -> HitlDecision:
    """
    Multi-factor HITL evaluation with structured output.

    Args:
        confidence_score: Model/extraction confidence in [0, 1] (values outside clamped).
        extracted_data: Structured extraction payload; may include required_keys.
        risk_level: low | medium | high | critical
        text_content: Raw or synthesized text to scan for policy/PII signals.
        source: Optional caller tag (e.g. "rag", "ingest", "extract").
        document_id: Optional document id for audit logs.
        collect_all: If True, run all rules and aggregate triggers; else fail-fast.
    """
    extracted_data = dict(extracted_data or {})
    try:
        conf = float(confidence_score)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    risk = (risk_level or "low").strip().lower()

    decision = HitlDecision(
        needs_review=False,
        reason="Passed automated verification",
        confidence_score=conf,
        risk_level=risk,
        metadata={
            "source": source,
            "document_id": document_id,
            "threshold": CONFIDENCE_THRESHOLD,
            "hitl_enabled": HITL_ENABLED,
        },
    )

    if not HITL_ENABLED:
        decision.reason = "HITL disabled via HITL_ENABLED"
        return decision

    if HITL_FORCE_REVIEW:
        decision.needs_review = True
        decision.reason = "HITL_FORCE_REVIEW is enabled"
        decision.triggers.append("force_review")
        decision.severity = "high"
        record_hitl_trigger("force_review")
        logger.warning("HITL Triggered: %s (doc=%s source=%s)", decision.reason, document_id, source)
        return decision

    triggers: list[str] = []
    reasons: list[str] = []
    severity = "none"

    def fire(category: str, reason: str, sev: str) -> None:
        nonlocal severity
        triggers.append(category)
        reasons.append(reason)
        severity = _bump_severity(severity, sev)
        record_hitl_trigger(category)
        logger.warning(
            "HITL Triggered [%s]: %s (doc=%s source=%s conf=%.3f risk=%s)",
            category,
            reason,
            document_id,
            source,
            conf,
            risk,
        )

    # Rule 1 — low confidence
    if conf < CONFIDENCE_THRESHOLD:
        fire(
            "low_confidence",
            f"Confidence score ({conf:.2f}) is below threshold ({CONFIDENCE_THRESHOLD})",
            "medium" if conf >= CONFIDENCE_THRESHOLD * 0.5 else "high",
        )
        if not collect_all:
            return _finalize(decision, True, reasons, triggers, severity)

    # Rule 2 — risk tier
    if risk in FORCE_RISK_LEVELS:
        fire(
            "high_risk_tier",
            f"Classified with high/critical risk level: {risk}",
            "critical" if risk == "critical" else "high",
        )
        if not collect_all:
            return _finalize(decision, True, reasons, triggers, severity)

    # Rule 3 — missing required extraction fields
    missing = _missing_required_fields(extracted_data)
    if missing:
        fire(
            "missing_required_field",
            f"Mandatory extraction field(s) missing: {', '.join(missing)}",
            "high",
        )
        if not collect_all:
            return _finalize(decision, True, reasons, triggers, severity)

    # Rule 4 — extraction anomalies
    anomalies = _anomalous_extraction(extracted_data)
    if anomalies:
        fire(
            "extraction_anomaly",
            f"Anomalous extraction signals: {', '.join(anomalies)}",
            "medium",
        )
        if not collect_all:
            return _finalize(decision, True, reasons, triggers, severity)

    # Text scans (capped)
    text = (text_content or "")[:MAX_TEXT_SCAN_CHARS]
    if text.strip():
        # Rule 5 — policy / threat keywords
        matched_kw = _scan_keywords(text)
        if matched_kw:
            fire(
                "policy_keyword_match",
                f"Detected sensitive policy/threat indicators: {', '.join(matched_kw)}",
                "high",
            )
            if not collect_all:
                return _finalize(decision, True, reasons, triggers, severity)

        # Rule 6 — PII / secrets patterns
        matched_pat = _scan_patterns(text)
        if matched_pat:
            fire(
                "pii_or_secret_detected",
                f"Detected potential sensitive patterns: {', '.join(matched_pat)}",
                "critical"
                if any(p in matched_pat for p in ("openai_sk_key", "private_key_block", "aws_access_key"))
                else "high",
            )
            if not collect_all:
                return _finalize(decision, True, reasons, triggers, severity)

    needs = bool(triggers)
    reason = (
        "; ".join(reasons)
        if needs
        else "Passed automated verification"
    )
    return _finalize(decision, needs, [reason] if needs else [reason], triggers, severity if needs else "none")


def _finalize(
    decision: HitlDecision,
    needs: bool,
    reasons: list[str],
    triggers: list[str],
    severity: str,
) -> HitlDecision:
    decision.needs_review = needs
    decision.reason = reasons[0] if reasons else decision.reason
    decision.triggers = list(triggers)
    decision.severity = severity
    decision.metadata["trigger_count"] = len(triggers)
    return decision


def should_queue_for_human(decision: HitlDecision | tuple[bool, str]) -> bool:
    """Convenience for routers/services."""
    if isinstance(decision, tuple):
        return bool(decision[0])
    return bool(decision.needs_review)


__all__ = [
    "CONFIDENCE_THRESHOLD",
    "HITL_ENABLED",
    "HitlDecision",
    "evaluate_for_review",
    "evaluate_for_review_detailed",
    "should_queue_for_human",
]
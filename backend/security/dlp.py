"""
Enterprise Data Loss Prevention (DLP) Engine.

Provides:
- PII and sensitive data detectors (emails, phones, SA IDs, US SSNs, IP addresses, passports, IBANs)
- API keys & credential detectors (GitHub, Slack, Stripe, OpenAI, AWS, JWTs)
- Luhn algorithm validation for credit card numbers
- Aggregate risk score calculation
- Inline text redaction
- Main scan orchestration and summary reporting
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CLASSIFICATION_LOW = "low"
CLASSIFICATION_MEDIUM = "medium"
CLASSIFICATION_HIGH = "high"
CLASSIFICATION_CRITICAL = "critical"


@dataclass
class DLPFinding:
    finding_type: str
    classification: str
    confidence: float
    value_masked: str
    start: int
    end: int


@dataclass
class DLPScanResult:
    pii_detected: bool
    risk_score: float
    total_findings: int
    findings: list[DLPFinding] = field(default_factory=list)

    def dict(self) -> dict[str, Any]:
        return {
            "pii_detected": self.pii_detected,
            "risk_score": self.risk_score,
            "total_findings": self.total_findings,
            "findings": [
                {
                    "finding_type": f.finding_type,
                    "classification": f.classification,
                    "confidence": f.confidence,
                    "value_masked": f.value_masked,
                    "start": f.start,
                    "end": f.end,
                }
                for f in self.findings
            ],
        }


def mask_value(val: str, visible: int = 4) -> str:
    """Mask sensitive string values while keeping a specified number of trailing characters visible."""
    if len(val) <= visible:
        return "*" * len(val)
    return "*" * (len(val) - visible) + val[-visible:]


def luhn_check(card_number: str) -> bool:
    """Validate credit card numbers using the Luhn algorithm checksum."""
    digits = [int(c) for c in card_number if c.isdigit()]
    if not digits:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def detect_emails(text: str) -> list[DLPFinding]:
    """Detect email addresses in text."""
    pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="email",
                classification=CLASSIFICATION_MEDIUM,
                confidence=0.95,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_phones(text: str) -> list[DLPFinding]:
    """Detect international and local South African phone numbers."""
    pattern = r"(?:\+27|0)\d{2}\s?\d{3}\s?\d{4}|\b\d{10}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="phone",
                classification=CLASSIFICATION_MEDIUM,
                confidence=0.90,
                value_masked=mask_value(val, 3),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_sa_ids(text: str) -> list[DLPFinding]:
    """Detect 13-digit South African ID numbers."""
    pattern = r"\b\d{13}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="sa_id",
                classification=CLASSIFICATION_HIGH,
                confidence=0.95,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_us_ssns(text: str) -> list[DLPFinding]:
    """Detect US Social Security Numbers (SSN)."""
    pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="us_ssn",
                classification=CLASSIFICATION_HIGH,
                confidence=0.95,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_github_keys(text: str) -> list[DLPFinding]:
    """Detect GitHub Personal Access Tokens."""
    pattern = r"\bghp_[a-zA-Z0-9]{36}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="github_token",
                classification=CLASSIFICATION_CRITICAL,
                confidence=1.0,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_slack_keys(text: str) -> list[DLPFinding]:
    """Detect Slack API/Bot tokens."""
    pattern = r"\bxoxb-[a-zA-Z0-9-]{10,}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="slack_token",
                classification=CLASSIFICATION_CRITICAL,
                confidence=1.0,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_stripe_keys(text: str) -> list[DLPFinding]:
    """Detect Stripe live/test API keys."""
    pattern = r"\br[a-z]_live_[a-zA-Z0-9]{20,}\b|\brk_live_[a-zA-Z0-9]{20,}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="stripe_key",
                classification=CLASSIFICATION_CRITICAL,
                confidence=1.0,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_ibans(text: str) -> list[DLPFinding]:
    """Detect International Bank Account Numbers (IBAN)."""
    pattern = r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="iban",
                classification=CLASSIFICATION_HIGH,
                confidence=0.90,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_jwts(text: str) -> list[DLPFinding]:
    """Detect JSON Web Tokens (JWT)."""
    pattern = r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="jwt_token",
                classification=CLASSIFICATION_HIGH,
                confidence=0.95,
                value_masked=mask_value(val, 6),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_openai_keys(text: str) -> list[DLPFinding]:
    """Detect OpenAI API keys."""
    pattern = r"\bsk-[a-zA-Z0-9_-]{20,}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="openai_api_key",
                classification=CLASSIFICATION_CRITICAL,
                confidence=1.0,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_aws_keys(text: str) -> list[DLPFinding]:
    """Detect AWS Access Key IDs."""
    pattern = r"\bAKIA[0-9A-Z]{16}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="aws_key",
                classification=CLASSIFICATION_CRITICAL,
                confidence=1.0,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_ips(text: str) -> list[DLPFinding]:
    """Detect IPv4 addresses."""
    pattern = r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="ip_address",
                classification=CLASSIFICATION_LOW,
                confidence=0.85,
                value_masked=mask_value(val, 4),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_passports(text: str) -> list[DLPFinding]:
    """Detect standard passport number formats."""
    pattern = r"\b[A-Z]\d{8}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        findings.append(
            DLPFinding(
                finding_type="passport",
                classification=CLASSIFICATION_HIGH,
                confidence=0.85,
                value_masked=mask_value(val, 3),
                start=match.start(),
                end=match.end(),
            )
        )
    return findings


def detect_credit_cards(text: str) -> list[DLPFinding]:
    """Detect credit card numbers verified with the Luhn algorithm."""
    pattern = r"\b(?:\d[ -]*){13,16}\b"
    findings = []
    for match in re.finditer(pattern, text):
        val = match.group(0)
        clean_card = re.sub(r"\D", "", val)
        if len(clean_card) >= 13 and luhn_check(clean_card):
            findings.append(
                DLPFinding(
                    finding_type="credit_card",
                    classification=CLASSIFICATION_CRITICAL,
                    confidence=0.95,
                    value_masked=mask_value(clean_card, 4),
                    start=match.start(),
                    end=match.end(),
                )
            )
    return findings


def calculate_risk_score(findings: list[DLPFinding]) -> float:
    """Calculate aggregate risk score based on finding classifications."""
    weights = {
        CLASSIFICATION_LOW: 0.05,
        CLASSIFICATION_MEDIUM: 0.10,
        CLASSIFICATION_HIGH: 0.20,
        CLASSIFICATION_CRITICAL: 0.30,
    }
    score = sum(weights.get(f.classification, 0.1) for f in findings)
    return round(min(score, 1.0), 2)


def redact_text(text: str) -> str:
    """Inline redaction of sensitive PII and tokens in text."""
    all_findings = []
    detectors = [
        detect_github_keys,
        detect_slack_keys,
        detect_stripe_keys,
        detect_openai_keys,
        detect_aws_keys,
        detect_credit_cards,
        detect_sa_ids,
        detect_us_ssns,
        detect_emails,
        detect_phones,
        detect_ibans,
        detect_jwts,
        detect_passports,
    ]
    for detector in detectors:
        all_findings.extend(detector(text))

    # Sort findings in reverse order of appearance to avoid index shifting during replacement
    sorted_findings = sorted(all_findings, key=lambda x: x.start, reverse=True)
    redacted = text
    for f in sorted_findings:
        redacted = (
            redacted[: f.start]
            + f"[REDACTED:{f.finding_type}]"
            + redacted[f.end :]
        )
    return redacted


def scan_dlp(text: str) -> DLPScanResult:
    """Orchestrate complete document DLP scan across all detectors."""
    all_findings = []
    detectors = [
        detect_emails,
        detect_phones,
        detect_sa_ids,
        detect_us_ssns,
        detect_github_keys,
        detect_slack_keys,
        detect_stripe_keys,
        detect_ibans,
        detect_jwts,
        detect_openai_keys,
        detect_aws_keys,
        detect_ips,
        detect_passports,
        detect_credit_cards,
    ]
    for detector in detectors:
        all_findings.extend(detector(text))

    risk_score = calculate_risk_score(all_findings)
    return DLPScanResult(
        pii_detected=len(all_findings) > 0,
        risk_score=risk_score,
        total_findings=len(all_findings),
        findings=all_findings,
    )


def summarize_findings(result: DLPScanResult) -> dict[str, Any]:
    """Generate summary breakdown of DLP findings by type."""
    breakdown: dict[str, int] = {}
    for f in result.findings:
        breakdown[f.finding_type] = breakdown.get(f.finding_type, 0) + 1

    return {
        "pii_detected": result.pii_detected,
        "total_findings": result.total_findings,
        "risk_score": result.risk_score,
        "breakdown": breakdown,
    }
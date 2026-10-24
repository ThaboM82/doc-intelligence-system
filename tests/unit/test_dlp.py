"""
Comprehensive Extended Unit Test Suite for Enterprise Data Loss Prevention (DLP).
Tests masking, Luhn algorithm validation, PII & credential detectors (including GitHub, Slack, Stripe, IBAN, US SSN),
risk score computation, main scan orchestration, inline text redaction, and summary reporting.
"""

from __future__ import annotations

import pytest

from backend.security.dlp import (
    CLASSIFICATION_CRITICAL,
    CLASSIFICATION_HIGH,
    CLASSIFICATION_MEDIUM,
    calculate_risk_score,
    detect_aws_keys,
    detect_credit_cards,
    detect_emails,
    detect_github_keys,
    detect_ibans,
    detect_ips,
    detect_jwts,
    detect_openai_keys,
    detect_passports,
    detect_phones,
    detect_sa_ids,
    detect_slack_keys,
    detect_stripe_keys,
    detect_us_ssns,
    luhn_check,
    mask_value,
    redact_text,
    scan_dlp,
    summarize_findings,
)


def test_mask_value() -> None:
    """Test string masking with default and custom visible counts."""
    assert mask_value("1234567890", visible=4) == "******7890"
    assert mask_value("secret", visible=2) == "****et"
    assert mask_value("abc", visible=4) == "***"


def test_luhn_check() -> None:
    """Test Luhn algorithm credit card validation."""
    valid_card = "453201511283036"
    assert luhn_check(valid_card) is True

    invalid_card = "453201511283035"
    assert luhn_check(invalid_card) is False


def test_detect_emails() -> None:
    """Test detection of email addresses."""
    text = "Contact support at admin@enterprise-sec.co.za or user.name+tag@gmail.com."
    findings = detect_emails(text)

    assert len(findings) == 2
    assert findings[0].finding_type == "email"
    assert findings[0].classification == CLASSIFICATION_MEDIUM
    assert "@" in findings[0].value_masked


def test_detect_phones() -> None:
    """Test detection of phone numbers."""
    text = "Call us at +27 11 123 4567 or 0821234567."
    findings = detect_phones(text)

    assert len(findings) >= 1
    assert any(f.finding_type == "phone" for f in findings)


def test_detect_sa_ids_and_us_ssns() -> None:
    """Test detection of South African IDs and US Social Security Numbers."""
    text = "SA ID: 8001015009088 and US SSN: 123-45-6789."
    sa_findings = detect_sa_ids(text)
    ssn_findings = detect_us_ssns(text)

    assert len(sa_findings) == 1
    assert sa_findings[0].finding_type == "sa_id"
    assert sa_findings[0].classification == CLASSIFICATION_HIGH

    assert len(ssn_findings) == 1
    assert ssn_findings[0].finding_type == "us_ssn"
    assert ssn_findings[0].classification == CLASSIFICATION_HIGH


def test_detect_advanced_tokens_and_keys() -> None:
    """Test detection of GitHub, Slack, and Stripe API keys/tokens."""
    text = (
        "GitHub: ghp_1234567890abcdefghijklmnopqrstuvwxyz123456, "
        "Slack: xoxb-1234567890-abcdef, "
        "Stripe: rk_live_TEST_INVALID"
    )
    
    gh_findings = detect_github_keys(text)
    slack_findings = detect_slack_keys(text)
    stripe_findings = detect_stripe_keys(text)

    assert len(gh_findings) == 1
    assert gh_findings[0].finding_type == "github_token"
    assert gh_findings[0].classification == CLASSIFICATION_CRITICAL

    assert len(slack_findings) == 1
    assert slack_findings[0].finding_type == "slack_token"
    assert slack_findings[0].classification == CLASSIFICATION_CRITICAL

    assert len(stripe_findings) == 1
    assert stripe_findings[0].finding_type == "stripe_key"
    assert stripe_findings[0].classification == CLASSIFICATION_CRITICAL


def test_detect_ibans() -> None:
    """Test detection of International Bank Account Numbers (IBAN)."""
    text = "Send funds to GB89BARC20041512345678 reference."
    findings = detect_ibans(text)

    assert len(findings) == 1
    assert findings[0].finding_type == "iban"
    assert findings[0].classification == CLASSIFICATION_HIGH


def test_detect_jwts_and_openai_aws() -> None:
    """Test detection of JWTs, OpenAI keys, and AWS keys."""
    token = "rk_live_TEST_MOCK_KEY_FOR_TESTING_PURPOSES_ONLY"
    text = f"Token: {token}, OpenAI: sk-proj-faketoken123456789abcdef, AWS: " + "AKIAIOSFODNN7EXAMPLE"

    assert len(detect_jwts(text)) == 1
    assert len(detect_openai_keys(text)) == 1
    assert len(detect_aws_keys(text)) == 1


def test_detect_ips_passports_and_cards() -> None:
    """Test IP addresses, passports, and credit cards."""
    text = "IP 192.168.1.100, Passport A12345678, Card 4532-0151-1283-036"
    
    assert len(detect_ips(text)) == 1
    assert len(detect_passports(text)) == 1
    assert len(detect_credit_cards(text)) == 1


def test_calculate_risk_score() -> None:
    """Test aggregate risk score calculation across findings."""
    from backend.security.dlp import DLPFinding

    findings = [
        DLPFinding("ip_address", "low", 0.9, "****1.100", 0, 10),
        DLPFinding("email", "medium", 0.95, "****@test.com", 12, 25),
        DLPFinding("openai_api_key", "critical", 1.0, "****wxyz", 27, 40),
    ]

    # Low (0.05) + Medium (0.10) + Critical (0.30) = 0.45
    score = calculate_risk_score(findings)
    assert score == 0.45


def test_redact_text() -> None:
    """Test inline text redaction of sensitive findings."""
    text = "User email is alice@company.com and card is 4532-0151-1283-036."
    redacted = redact_text(text)

    assert "alice@company.com" not in redacted
    assert "4532-0151-1283-036" not in redacted
    assert "[REDACTED:email]" in redacted
    assert "[REDACTED:credit_card]" in redacted


def test_scan_dlp_orchestration() -> None:
    """Test complete document DLP scan orchestration and dictionary serialization."""
    document_text = """
    Confidential Report
    Email: manager@company.com
    SA ID: 8001015009088
    GitHub: ghp_1234567890abcdefghijklmnopqrstuvwxyz123456
    """

    result = scan_dlp(document_text)

    assert result.pii_detected is True
    assert result.total_findings >= 3
    assert result.risk_score > 0.0

    res_dict = result.dict()
    assert "findings" in res_dict
    assert "risk_score" in res_dict
    assert "total_findings" in res_dict
    assert "pii_detected" in res_dict


def test_summarize_findings() -> None:
    """Test summary generation breakdown."""
    document_text = "Contact test@example.com or support@example.com from IP 10.0.0.1."
    result = scan_dlp(document_text)
    summary = summarize_findings(result)

    assert summary["pii_detected"] is True
    assert summary["total_findings"] >= 3
    assert "breakdown" in summary
    assert summary["breakdown"]["email"] == 2
    assert summary["breakdown"]["ip_address"] == 1
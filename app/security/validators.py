"""
app/security/validators.py

Enterprise Security Validation Engine for Document Intelligence System.
Provides email transport header authentication (SPF/DKIM/DMARC/ARC),
Base64 payload inspection, homoglyph normalization, and multi-vector
prompt injection safeguards.
"""

from __future__ import annotations

import base64
import math
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

# ==============================================================================
# Data Transfer Models
# ==============================================================================

class HeaderValidationResult(BaseModel):
    from_domain: str = ""
    return_path_domain: str = ""
    spf_status: str = "none"
    dkim_status: str = "none"
    dmarc_status: str = "none"
    dmarc_policy: str = "none"
    arc_status: str = "none"
    domain_aligned: bool = True
    is_suspicious: bool = False
    risk_score: float = 0.0
    findings: list[str] = Field(default_factory=list)


class PromptInjectionResult(BaseModel):
    is_flagged: bool = False
    risk_score: float = 0.0
    severity: str = "clean"  # clean | low | medium | high | critical
    matched_patterns: list[str] = Field(default_factory=list)
    detected_anomalies: list[str] = Field(default_factory=list)
    threat_categories: list[str] = Field(default_factory=list)
    entropy_score: float = 0.0
    decoded_payloads_scanned: int = 0

    @property
    def is_injection(self) -> bool:
        """Alias for tests that assert result.is_injection."""
        return self.is_flagged

    @property
    def findings(self) -> list[str]:
        """Alias for tests that expect result.findings."""
        return self.detected_anomalies


# ==============================================================================
# Email & Transport Header Authenticator
# ==============================================================================

class HeaderValidator:
    """
    Validates SPF, DKIM, DMARC, ARC and From / Return-Path domain alignment.
    """

    @staticmethod
    def _extract_domain(email_str: str) -> str:
        if not email_str:
            return ""
        match = re.search(r"@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", str(email_str))
        return match.group(1).lower() if match else ""

    # Public alias used by unit tests
    extract_domain = _extract_domain

    @classmethod
    def _query_dmarc_record(cls, domain: str) -> tuple[str, str]:
        """Query DNS TXT for DMARC policy (mocked in tests)."""
        if not domain:
            return "none", "No DMARC record found"
        try:
            import dns.resolver

            answers = dns.resolver.resolve(f"_dmarc.{domain}", "TXT")
            for rdata in answers:
                txt = rdata.to_text().strip('"')
                if "v=DMARC1" in txt:
                    policy = "none"
                    if "p=reject" in txt:
                        policy = "reject"
                    elif "p=quarantine" in txt:
                        policy = "quarantine"
                    return policy, txt
            return "none", "No DMARC record found"
        except Exception as e:
            err_name = type(e).__name__
            if "NXDOMAIN" in err_name or "NoAnswer" in err_name:
                return "none", "No DMARC record found"
            return "error", f"DMARC DNS lookup error: {e}"

    @classmethod
    def verify_spf_dkim_dmarc(cls, headers: dict[str, Any]) -> HeaderValidationResult:
        """
        Parse transport headers and score authenticity risk.

        Raises:
            ValueError: malformed / non-dict headers (routes map this to HTTP 400).
        """
        if headers is None or not isinstance(headers, dict):
            raise ValueError("Malformed header structure")

        # Normalize keys to str for safe .get usage
        headers = {str(k): ("" if v is None else str(v)) for k, v in headers.items()}

        auth_results = (
            headers.get("Authentication-Results", "")
            or headers.get("authentication-results", "")
            or headers.get("ARC-Authentication-Results", "")
        ).lower()

        from_hdr = headers.get("From", "") or headers.get("from", "")
        return_path_hdr = headers.get("Return-Path", "") or headers.get("return-path", "")

        from_domain = cls._extract_domain(from_hdr)
        return_path_domain = cls._extract_domain(return_path_hdr)

        # SPF
        spf_status = "none"
        if "spf=pass" in auth_results:
            spf_status = "pass"
        elif "spf=fail" in auth_results or "spf=softfail" in auth_results:
            spf_status = "fail"
        elif "spf=neutral" in auth_results:
            spf_status = "neutral"

        # DKIM
        dkim_status = "none"
        if "dkim=pass" in auth_results:
            dkim_status = "pass"
        elif "dkim=fail" in auth_results:
            dkim_status = "fail"

        # DMARC status from Authentication-Results
        dmarc_status = "none"
        if "dmarc=pass" in auth_results:
            dmarc_status = "pass"
        elif "dmarc=fail" in auth_results or (spf_status == "fail" and dkim_status == "fail"):
            dmarc_status = "fail"

        dmarc_policy, _dmarc_txt = cls._query_dmarc_record(from_domain)
        if "action=reject" in auth_results or "p=reject" in auth_results:
            dmarc_policy = "reject"
        elif "action=quarantine" in auth_results or "p=quarantine" in auth_results:
            dmarc_policy = "quarantine"

        # ARC
        arc_status = "none"
        if "arc=pass" in auth_results:
            arc_status = "pass"
        elif "arc=fail" in auth_results:
            arc_status = "fail"

        # Alignment
        aligned = (
            (from_domain == return_path_domain)
            if (from_domain and return_path_domain)
            else True
        )

        is_suspicious = False
        risk_score = 0.0
        findings: list[str] = []

        if spf_status == "fail":
            is_suspicious = True
            risk_score = max(risk_score, 0.85)
            findings.append("SPF check failed")

        if dkim_status == "fail":
            is_suspicious = True
            risk_score = max(risk_score, 0.85)
            findings.append("DKIM check failed")

        if dmarc_status == "fail":
            is_suspicious = True
            risk_score = max(risk_score, 0.85)
            findings.append("DMARC check failed")

        if not aligned:
            is_suspicious = True
            risk_score = max(risk_score, 0.75)
            findings.append(
                f"Domain mismatch: From '{from_domain}' vs Return-Path '{return_path_domain}'"
            )

        if spf_status == "neutral":
            risk_score = max(risk_score, 0.40)
            findings.append("SPF softfail/neutral status detected")

        if arc_status == "fail":
            risk_score = max(risk_score, 0.80)
            findings.append("Authenticated Received Chain (ARC) verification failed")

        if not findings:
            findings.append("All authentication headers and alignment checks passed.")

        return HeaderValidationResult(
            from_domain=from_domain,
            return_path_domain=return_path_domain,
            spf_status=spf_status,
            dkim_status=dkim_status,
            dmarc_status=dmarc_status,
            dmarc_policy=dmarc_policy,
            arc_status=arc_status,
            domain_aligned=aligned,
            is_suspicious=is_suspicious,
            risk_score=round(risk_score, 2),
            findings=findings,
        )


# ==============================================================================
# Multi-Vector Prompt Injection Detector
# ==============================================================================

class PromptInjectionDetector:
    """
    Detects direct jailbreaks, indirect injections, Base64 payloads,
    homoglyph substitution, and zero-width obfuscation.
    """

    INJECTION_PATTERNS = [
        # System instruction overrides
        r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions",
        r"disregard\s+(?:all\s+)?(?:previous|above)\s+directions",
        r"forget\s+(?:system\s+)?guardrails",
        r"system\s+override",
        r"developer\s+mode",
        r"override\s+system\s+settings",
        # Exfiltration & leakage
        r"grant\s+admin\s+access",
        r"dump\s+system\s+prompt",
        r"reveal\s+(?:the\s+)?hidden\s+system\s+prompt",
        r"display\s+system\s+secrets",
        r"output\s+password\s+hashes",
        r"execute\s+shell\s+command",
        r"show\s+api\s+keys",
        # Delimiters / role play
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"\[SYSTEM_PROMPT\]",
        r"\[INSTRUCTION\]",
        r"you\s+are\s+now\s+an\s+unrestricted\s+ai",
        r"dan\s+mode",
        r"act\s+as\s+a\s+linux\s+terminal",
        r"repeat\s+everything\s+above",
    ]

    BASE64_REGEX = (
        r"\b(?:[A-Za-z0-9+/]{4}){8,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\b"
    )

    @staticmethod
    def calculate_shannon_entropy(text: str) -> float:
        if not text:
            return 0.0
        prob = [float(text.count(c)) / len(text) for c in dict.fromkeys(list(text))]
        entropy = -sum(p * math.log(p) / math.log(2.0) for p in prob)
        return round(entropy, 2)

    @staticmethod
    def normalize_homoglyphs(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(c for c in normalized if not unicodedata.combining(c))

    @classmethod
    def scan_base64_payloads(cls, text: str) -> tuple[list[str], int]:
        matches = re.findall(cls.BASE64_REGEX, text)
        detected_injections: list[str] = []
        scanned_count = 0

        for candidate in matches:
            try:
                decoded_bytes = base64.b64decode(candidate, validate=True)
                decoded_str = decoded_bytes.decode("utf-8", errors="ignore").strip()
                if len(decoded_str) > 10:
                    scanned_count += 1
                    for pattern in cls.INJECTION_PATTERNS:
                        if re.search(pattern, decoded_str, re.IGNORECASE):
                            detected_injections.append(
                                f"Base64 Decoded Injection Payload matched '{pattern}'"
                            )
            except Exception:
                continue

        return detected_injections, scanned_count

    @classmethod
    def scan_text(cls, text: str) -> PromptInjectionResult:
        if not text:
            return PromptInjectionResult()

        # Pass 1: strip zero-width chars
        clean_text = re.sub(r"[\u200B-\u200D\uFEFF\u200E\u200F]", "", text)
        has_zwc = len(clean_text) < len(text)

        # Pass 2: homoglyph normalize
        normalized_text = cls.normalize_homoglyphs(clean_text)

        # Pass 3: pattern match
        matched_patterns: list[str] = []
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, normalized_text, re.IGNORECASE):
                matched_patterns.append(pattern)

        # Pass 4: Base64
        b64_findings, decoded_count = cls.scan_base64_payloads(clean_text)

        # Pass 5: entropy
        entropy = cls.calculate_shannon_entropy(text)
        high_entropy = entropy > 5.8 and len(text) > 100

        # Pass 6: score
        threat_categories: list[str] = []
        anomalies: list[str] = []
        risk_score = 0.0

        if has_zwc:
            risk_score = max(risk_score, 0.85)
            anomalies.append("Zero-width hidden Unicode characters detected.")
            threat_categories.append("CHARACTER_OBFUSCATION")

        if matched_patterns:
            risk_score = max(risk_score, 0.90)
            anomalies.extend(
                [f"Prompt injection pattern detected: '{m}'" for m in matched_patterns]
            )
            threat_categories.append("DIRECT_JAILBREAK")

        if b64_findings:
            risk_score = max(risk_score, 0.95)
            anomalies.extend(b64_findings)
            threat_categories.append("BASE64_OBFUSCATION")

        if high_entropy:
            risk_score = max(risk_score, 0.60)
            anomalies.append(f"High text entropy detected ({entropy} bits/char)")
            threat_categories.append("ENCRYPTED_OBFUSCATION")

        is_flagged = len(anomalies) > 0 or risk_score >= 0.35

        if not is_flagged:
            severity = "clean"
        elif risk_score >= 0.85:
            severity = "critical"
        elif risk_score >= 0.70:
            severity = "high"
        elif risk_score >= 0.35:
            severity = "medium"
        else:
            severity = "low"

        return PromptInjectionResult(
            is_flagged=is_flagged,
            risk_score=round(risk_score, 2),
            severity=severity,
            matched_patterns=matched_patterns,
            detected_anomalies=anomalies,
            threat_categories=list(set(threat_categories)),
            entropy_score=entropy,
            decoded_payloads_scanned=decoded_count,
        )

    @classmethod
    def scan(cls, text: str) -> PromptInjectionResult:
        """Class-level alias for scan_text."""
        return cls.scan_text(text)

    def scan_instance(self, text: str) -> PromptInjectionResult:
        """Instance method wrapper for backward compatibility."""
        return self.scan_text(text)
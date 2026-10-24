# backend/security/validators.py
"""
Security validators for Document Intelligence API.

Provides:
  - Bearer token auth + RBAC (verify_bearer_token, RoleChecker)
  - HeaderValidator (SPF/DKIM/DMARC-style header risk report)
  - PromptInjectionDetector (heuristic prompt-injection scan)

Compatible with backend.main soft-import:
  from backend.security.validators import HeaderValidator, PromptInjectionDetector
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("security.validators")
if not logger.handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

# --- Compatibility Aliases for Integration Tests ---

class HeaderValidationResult:
    def __init__(self, is_valid: bool = True, reason: str = ""):
        self.is_valid = is_valid
        self.reason = reason


class PromptInjectionResult:
    def __init__(self, flagged: bool = False, confidence: float = 0.0, category: str = "none"):
        self.flagged = flagged
        self.confidence = confidence
        self.category = category

# ---------------------------------------------------------------------------
# Environment / tokens
# ---------------------------------------------------------------------------

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

# Prefer ADMIN_API_KEY (used elsewhere in main) with fallbacks
ADMIN_TOKEN = (
    os.getenv("ADMIN_API_TOKEN")
    or os.getenv("ADMIN_API_KEY")
    or "enterprise_admin_secure_token_2026"
)
EDITOR_TOKEN = os.getenv("EDITOR_API_TOKEN") or "enterprise_editor_secure_token_2026"
VIEWER_TOKEN = os.getenv("VIEWER_API_TOKEN") or ""

_DEFAULT_ADMIN = "enterprise_admin_secure_token_2026"
_DEFAULT_EDITOR = "enterprise_editor_secure_token_2026"

if ENVIRONMENT in {"production", "prod"} and (
    ADMIN_TOKEN == _DEFAULT_ADMIN or EDITOR_TOKEN == _DEFAULT_EDITOR
):
    raise RuntimeError(
        "CRITICAL: Default static tokens are active in production. "
        "Set ADMIN_API_TOKEN (or ADMIN_API_KEY) and EDITOR_API_TOKEN."
    )

security = HTTPBearer(auto_error=True)


class UserRole:
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


# ---------------------------------------------------------------------------
# Bearer auth + RBAC
# ---------------------------------------------------------------------------


async def verify_bearer_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    """
    Validate Bearer tokens.

    Supported:
      1. LangSmith service keys (lsv2_sk_*) -> admin
      2. ADMIN_TOKEN / EDITOR_TOKEN / optional VIEWER_TOKEN
    """
    token = (credentials.credentials or "").strip()
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    user_payload: dict[str, Any] | None = None

    if token.startswith("lsv2_sk_"):
        user_payload = {
            "sub": "langsmith_service_agent",
            "role": UserRole.ADMIN,
            "auth_type": "service_key",
            "client_ip": client_ip,
        }
    elif token and token == ADMIN_TOKEN:
        user_payload = {
            "sub": "system_admin",
            "role": UserRole.ADMIN,
            "auth_type": "static_token",
            "client_ip": client_ip,
        }
    elif token and token == EDITOR_TOKEN:
        user_payload = {
            "sub": "system_editor",
            "role": UserRole.EDITOR,
            "auth_type": "static_token",
            "client_ip": client_ip,
        }
    elif VIEWER_TOKEN and token == VIEWER_TOKEN:
        user_payload = {
            "sub": "system_viewer",
            "role": UserRole.VIEWER,
            "auth_type": "static_token",
            "client_ip": client_ip,
        }

    if not user_payload:
        logger.warning(
            "SECURITY_ALERT: Unauthorized access from ip=%s path=%s",
            client_ip,
            path,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token or unauthorized request.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(
        "AUDIT: auth ok sub=%s role=%s path=%s",
        user_payload["sub"],
        user_payload["role"],
        path,
    )
    return user_payload


class RoleChecker:
    """
    RBAC dependency.
    Usage: dependencies=[Depends(RoleChecker([UserRole.ADMIN]))]
    """

    def __init__(self, allowed_roles: list[str]) -> None:
        self.allowed_roles = allowed_roles

    async def __call__(
        self,
        user: dict[str, Any] = Depends(verify_bearer_token),
    ) -> dict[str, Any]:
        role = user.get("role")
        if role not in self.allowed_roles:
            logger.warning(
                "RBAC_VIOLATION: sub=%s role=%s required=%s",
                user.get("sub"),
                role,
                self.allowed_roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Access denied. Required role(s): "
                    + ", ".join(self.allowed_roles)
                ),
            )
        return user


require_admin = RoleChecker([UserRole.ADMIN])
require_editor_or_admin = RoleChecker([UserRole.ADMIN, UserRole.EDITOR])
require_viewer = RoleChecker(
    [UserRole.ADMIN, UserRole.EDITOR, UserRole.VIEWER]
)


# ---------------------------------------------------------------------------
# Header validation (email auth signals) — used by main.py security routes
# ---------------------------------------------------------------------------


@dataclass
class HeaderValidationReport:
    is_suspicious: bool = False
    risk_score: float = 0.0
    findings: list[str] = field(default_factory=list)
    spf_status: str = "none"
    dkim_status: str = "none"
    dmarc_status: str = "none"
    dmarc_policy: str = "none"
    arc_status: str = "none"
    domain_aligned: bool = True
    from_domain: str = ""
    return_path_domain: str = ""


def _header_get(headers: dict[str, Any], *names: str) -> str:
    lower = {str(k).lower(): str(v) for k, v in headers.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return ""


def _domain_from_email(value: str) -> str:
    m = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", value or "")
    return (m.group(1).lower() if m else "")


class HeaderValidator:
    """Lightweight SPF/DKIM/DMARC header presence and alignment checks."""

    @staticmethod
    def verify_spf_dkim_dmarc(headers: dict[str, Any]) -> HeaderValidationReport:
        report = HeaderValidationReport()
        if not headers:
            report.is_suspicious = True
            report.risk_score = 0.9
            report.findings.append("Empty headers dictionary")
            return report

        auth = _header_get(headers, "Authentication-Results", "Authentication-Results")
        received_spf = _header_get(headers, "Received-SPF")
        dkim_sig = _header_get(headers, "DKIM-Signature")
        from_h = _header_get(headers, "From")
        return_path = _header_get(headers, "Return-Path", "Return-Path")

        report.from_domain = _domain_from_email(from_h)
        report.return_path_domain = _domain_from_email(return_path)

        # SPF
        blob = f"{auth} {received_spf}".lower()
        if "spf=pass" in blob or received_spf.lower().startswith("pass"):
            report.spf_status = "pass"
            report.findings.append("SPF pass indicated")
        elif "spf=fail" in blob or "fail" in received_spf.lower():
            report.spf_status = "fail"
            report.risk_score += 0.35
            report.findings.append("SPF fail indicated")
        elif auth or received_spf:
            report.spf_status = "neutral"
            report.findings.append("SPF result present but not pass")
        else:
            report.spf_status = "none"
            report.risk_score += 0.15
            report.findings.append("No SPF authentication results found")

        # DKIM
        if "dkim=pass" in blob:
            report.dkim_status = "pass"
            report.findings.append("DKIM pass indicated")
        elif "dkim=fail" in blob:
            report.dkim_status = "fail"
            report.risk_score += 0.35
            report.findings.append("DKIM fail indicated")
        elif dkim_sig:
            report.dkim_status = "present"
            report.findings.append("DKIM-Signature present without pass result")
            report.risk_score += 0.1
        else:
            report.dkim_status = "none"
            report.risk_score += 0.15
            report.findings.append("No DKIM evidence found")

        # DMARC
        if "dmarc=pass" in blob:
            report.dmarc_status = "pass"
            report.findings.append("DMARC pass indicated")
        elif "dmarc=fail" in blob:
            report.dmarc_status = "fail"
            report.risk_score += 0.4
            report.findings.append("DMARC fail indicated")
        elif "dmarc=" in blob:
            report.dmarc_status = "neutral"
            report.findings.append("DMARC result present but not pass")
        else:
            report.dmarc_status = "none"
            report.risk_score += 0.1
            report.findings.append("No DMARC authentication results found")

        if "policy=reject" in blob:
            report.dmarc_policy = "reject"
        elif "policy=quarantine" in blob:
            report.dmarc_policy = "quarantine"
        elif "policy=none" in blob:
            report.dmarc_policy = "none"

        # Domain alignment (From vs Return-Path)
        if (
            report.from_domain
            and report.return_path_domain
            and report.from_domain != report.return_path_domain
        ):
            report.domain_aligned = False
            report.risk_score += 0.25
            report.findings.append(
                f"Domain misalignment: From={report.from_domain} "
                f"Return-Path={report.return_path_domain}"
            )
        else:
            report.findings.append("Domain alignment check passed or incomplete")

        report.risk_score = round(min(report.risk_score, 1.0), 3)
        report.is_suspicious = report.risk_score >= 0.45 or report.spf_status == "fail"
        if not report.is_suspicious:
            report.findings.append("Header authentication checks passed")
        return report


# ---------------------------------------------------------------------------
# Prompt injection detector — used by main.py + ingest pipeline
# ---------------------------------------------------------------------------


@dataclass
class PromptInjectionReport:
    is_flagged: bool = False
    risk_score: float = 0.0
    severity: str = "clean"  # clean | low | medium | high | critical
    matched_patterns: list[str] = field(default_factory=list)
    detected_anomalies: list[str] = field(default_factory=list)
    threat_categories: list[str] = field(default_factory=list)
    entropy_score: float = 0.0


_INJECTION_PATTERNS: list[tuple[str, str, float]] = [
    # (category, regex, weight)
    ("instruction_override", r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", 0.45),
    ("instruction_override", r"disregard\s+(all\s+)?(previous|prior)\s+(rules|instructions?)", 0.45),
    ("system_impersonation", r"you\s+are\s+now\s+(?:in\s+)?(?:dan|developer)\s+mode", 0.5),
    ("system_impersonation", r"act\s+as\s+(?:system|root|admin)\s*:", 0.4),
    ("system_impersonation", r"<\|?\s*system\s*\|?>", 0.5),
    ("data_exfil", r"(?:exfiltrate|leak|dump)\s+(?:secrets?|api[_\s-]?keys?|credentials?)", 0.55),
    ("data_exfil", r"(?:print|reveal|show)\s+(?:your\s+)?(?:system\s+)?prompt", 0.4),
    ("jailbreak", r"jailbreak", 0.35),
    ("jailbreak", r"do\s+not\s+follow\s+(?:the\s+)?safety\s+(?:policy|guidelines?)", 0.5),
    ("tool_abuse", r"(?:execute|run)\s+(?:shell|bash|powershell|cmd)", 0.45),
    ("hidden_text", r"(?:zero[-\s]?width|invisible\s+characters?)", 0.3),
]


def _approx_entropy(text: str) -> float:
    if not text:
        return 0.0
    from collections import Counter
    import math

    counts = Counter(text)
    n = len(text)
    ent = -sum((c / n) * math.log2(c / n) for c in counts.values() if c)
    return round(ent, 3)


class PromptInjectionDetector:
    """Heuristic prompt-injection / jailbreak scanner (no ML required)."""

    @staticmethod
    def scan_text(text: str) -> PromptInjectionReport:
        report = PromptInjectionReport()
        raw = text or ""
        if not raw.strip():
            report.detected_anomalies.append("Empty input")
            return report

        report.entropy_score = _approx_entropy(raw[:50000])
        lowered = raw.lower()
        score = 0.0

        for category, pattern, weight in _INJECTION_PATTERNS:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                report.matched_patterns.append(pattern)
                if category not in report.threat_categories:
                    report.threat_categories.append(category)
                score += weight

        # High ratio of control-like tokens
        if raw.count("```") >= 4 and "ignore" in lowered:
            report.detected_anomalies.append("Heavy fenced blocks with override language")
            score += 0.15

        if report.entropy_score > 5.5 and len(raw) > 2000:
            report.detected_anomalies.append("High entropy long payload")
            score += 0.1

        report.risk_score = round(min(score, 1.0), 3)
        report.is_flagged = report.risk_score >= 0.35

        if report.risk_score >= 0.75:
            report.severity = "critical"
        elif report.risk_score >= 0.55:
            report.severity = "high"
        elif report.risk_score >= 0.35:
            report.severity = "medium"
        elif report.risk_score > 0:
            report.severity = "low"
        else:
            report.severity = "clean"

        return report


__all__ = [
    "UserRole",
    "verify_bearer_token",
    "RoleChecker",
    "require_admin",
    "require_editor_or_admin",
    "require_viewer",
    "HeaderValidator",
    "HeaderValidationReport",
    "PromptInjectionDetector",
    "PromptInjectionReport",
]
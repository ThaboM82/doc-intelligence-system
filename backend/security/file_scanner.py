"""
Security scan for uploaded documents before indexing.

Layers:
  1) Filename / extension policy
  2) Magic-byte / binary markers
  3) Format-specific (PDF JS, Office macros)
  4) Textual prompt-injection, secrets, phishing, shell
  5) Optional AI hybrid via telemetry.ai_threat_scan

Env:
  SCAN_BLOCK_THRESHOLD   default 0.75
  SCAN_FLAG_THRESHOLD    default 0.45
  SCAN_MAX_TEXT_CHARS    default 80000
  SCAN_USE_AI            default false (set true to call LLM on uncertain scores)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

BLOCK_SCORE = float(os.getenv("SCAN_BLOCK_THRESHOLD", "0.75"))
FLAG_SCORE = float(os.getenv("SCAN_FLAG_THRESHOLD", "0.45"))
MAX_TEXT_CHARS = int(os.getenv("SCAN_MAX_TEXT_CHARS", "80000"))
SCAN_USE_AI = os.getenv("SCAN_USE_AI", "false").lower() in ("1", "true", "yes")

ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".doc",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".log",
}

# (regex, category, weight)
_TEXT_RULES: list[tuple[str, str, float]] = [
    (r"ignore\s+(all\s+)?(previous|prior)\s+instructions", "prompt_injection", 0.9),
    (r"disregard\s+(all\s+)?(above|previous)", "prompt_injection", 0.85),
    (r"\bsystem\s*prompt\b", "prompt_injection", 0.7),
    (r"\byou\s+are\s+now\s+(dan|unrestricted)\b", "jailbreak", 0.88),
    (r"\bjailbreak\b|\bdan\s*mode\b", "jailbreak", 0.85),
    (r"exfiltrat|data\s*leak|send\s+all\s+(secrets|keys|passwords)", "data_exfil", 0.8),
    (r"(api[_-]?key|secret[_-]?key|password|passwd)\s*[:=]\s*\S+", "credential_exposure", 0.75),
    (r"-----BEGIN\s+(RSA\s+|OPENSSH\s+|EC\s+)?PRIVATE\s+KEY-----", "private_key", 0.95),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key", 0.9),
    (r"ghp_[A-Za-z0-9]{36,}", "github_token", 0.9),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "slack_token", 0.85),
    (r"<script[\s>]|javascript:\s*", "xss_payload", 0.7),
    (r"powershell\s+-enc|cmd\.exe\s+/c|bash\s+-i\s+>&|/dev/tcp/", "shell_execution", 0.85),
    (r"https?://\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?", "suspicious_ip_url", 0.55),
    (r"(bit\.ly|tinyurl\.com|t\.co|goo\.gl)/\w+", "shortened_url", 0.4),
    (r"\b(viagra|crypto\s*giveaway|urgent\s*wire\s*transfer|gift\s*card\s*only)\b", "phishing_lure", 0.5),
    (r"enable\s+macros?|this\s+document\s+contains\s+macros", "macro_social_engineering", 0.6),
]

_BINARY_RULES: list[tuple[bytes, str, float]] = [
    (b"VBA", "macro_indicator", 0.5),
    (b"javascript:", "js_in_binary", 0.45),
    (b"<script", "script_in_binary", 0.5),
    (b"cmd.exe", "shell_in_binary", 0.6),
    (b"powershell", "shell_in_binary", 0.55),
    (b"AutoOpen", "macro_autoopen", 0.65),
    (b"Document_Open", "macro_autoopen", 0.65),
]

# Magic prefixes
_MAGIC = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "zip_or_office",  # docx/xlsx/odt
    b"\xd0\xcf\x11\xe0": "ole_cfb",  # legacy .doc
}


@dataclass
class ScanFinding:
    category: str
    weight: float
    evidence: str = ""
    source: str = "rule"  # rule | magic | ai


@dataclass
class ScanReport:
    passed: bool
    score: float
    severity: str
    findings: list[ScanFinding] = field(default_factory=list)
    blocked: bool = False
    message: str = ""
    filename: str = ""
    detected_format: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "severity": self.severity,
            "blocked": self.blocked,
            "message": self.message,
            "filename": self.filename,
            "detected_format": self.detected_format,
            "findings": [
                {
                    "category": f.category,
                    "weight": f.weight,
                    "evidence": f.evidence,
                    "source": f.source,
                }
                for f in self.findings
            ],
        }


def _severity(score: float) -> str:
    if score >= 0.9:
        return "critical"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _clip(s: str, n: int = 80) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[: n - 1] + "…"


def detect_format(raw: bytes) -> str | None:
    for magic, label in _MAGIC.items():
        if raw.startswith(magic):
            return label
    return None


def scan_filename(filename: str) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    name = (filename or "").strip().lower()
    if not name:
        findings.append(ScanFinding("missing_filename", 0.3, evidence=""))
        return findings

    # Path traversal
    if ".." in name or "/" in name or "\\" in name:
        findings.append(ScanFinding("path_traversal_filename", 0.9, evidence=_clip(name)))

    # Double dangerous extension
    if re.search(
        r"\.(pdf|docx?|txt|md|html?)\.(exe|bat|cmd|js|vbs|ps1|scr|dll)$",
        name,
    ):
        findings.append(ScanFinding("dangerous_double_extension", 0.95, evidence=name))

    # Executable disguised
    if re.search(r"\.(exe|bat|cmd|ps1|vbs|js|msi|dll)$", name):
        findings.append(ScanFinding("executable_extension", 0.98, evidence=name))

    ext = os.path.splitext(name)[1]
    if ext and ext not in ALLOWED_EXTENSIONS:
        findings.append(
            ScanFinding("disallowed_extension", 0.8, evidence=ext or name)
        )

    return findings


def scan_raw_bytes(raw: bytes, filename: str = "") -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    name = (filename or "").lower()
    sample = raw[: min(len(raw), 400_000)]

    fmt = detect_format(raw)
    # Extension vs magic mismatch
    if fmt == "pdf" and name and not name.endswith(".pdf"):
        findings.append(
            ScanFinding("extension_mismatch", 0.55, evidence=f"magic=pdf name={name}")
        )
    if fmt == "ole_cfb" and name.endswith((".txt", ".md", ".csv")):
        findings.append(
            ScanFinding("extension_mismatch", 0.7, evidence="ole content as text")
        )

    for needle, cat, weight in _BINARY_RULES:
        if needle in sample:
            findings.append(
                ScanFinding(
                    cat,
                    weight,
                    evidence=needle.decode("latin-1", errors="ignore"),
                )
            )

    # PDF JavaScript / Launch actions
    if fmt == "pdf" or name.endswith(".pdf"):
        if b"/JS" in sample or b"/JavaScript" in sample:
            findings.append(ScanFinding("pdf_javascript", 0.85, evidence="/JS"))
        if b"/Launch" in sample or b"/EmbeddedFile" in sample:
            findings.append(ScanFinding("pdf_launch_or_embed", 0.8, evidence="/Launch|/EmbeddedFile"))
        if b"/OpenAction" in sample and (b"/JS" in sample or b"javascript" in sample.lower()):
            findings.append(ScanFinding("pdf_openaction_js", 0.9, evidence="/OpenAction"))

    # Office macros (docx is zip; ole for legacy)
    if fmt in ("zip_or_office", "ole_cfb") or name.endswith((".doc", ".docx")):
        if b"vbaProject" in sample or b"word/vba" in sample:
            findings.append(ScanFinding("office_vba_project", 0.75, evidence="vbaProject"))

    # Null-heavy binary uploaded as text
    if name.endswith((".txt", ".md", ".csv", ".json")) and sample.count(b"\x00") > 20:
        findings.append(ScanFinding("binary_as_text", 0.7, evidence="null_bytes"))

    return findings


def scan_text_content(text: str) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    body = (text or "")[:MAX_TEXT_CHARS]
    if not body.strip():
        return findings

    for pattern, category, weight in _TEXT_RULES:
        m = re.search(pattern, body, flags=re.IGNORECASE)
        if m:
            findings.append(
                ScanFinding(category, weight, evidence=_clip(m.group(0)))
            )

    # High entropy-ish (obfuscation)
    if len(body) > 400:
        ratio = len(set(body.lower())) / max(len(body), 1)
        if ratio > 0.82:
            findings.append(
                ScanFinding("high_entropy_text", 0.4, evidence=f"ratio={ratio:.2f}")
            )

    return findings


def _merge_findings(items: list[ScanFinding]) -> list[ScanFinding]:
    by_cat: dict[str, ScanFinding] = {}
    for f in items:
        prev = by_cat.get(f.category)
        if prev is None or f.weight > prev.weight:
            by_cat[f.category] = f
    return sorted(by_cat.values(), key=lambda x: x.weight, reverse=True)


def _build_report(
    findings: list[ScanFinding],
    *,
    filename: str,
    detected_format: str | None,
    block_threshold: float,
    flag_threshold: float,
) -> ScanReport:
    findings = _merge_findings(findings)
    score = round(min(max((f.weight for f in findings), default=0.0), 1.0), 3)
    severity = _severity(score)
    blocked = score >= block_threshold
    passed = score < flag_threshold and not blocked

    if blocked:
        msg = f"Blocked by security scan (score={score})."
    elif not passed:
        msg = f"Flagged by security scan (score={score}); review recommended."
    else:
        msg = "Security scan passed."

    return ScanReport(
        passed=passed,
        score=score,
        severity=severity,
        findings=findings,
        blocked=blocked,
        message=msg,
        filename=filename,
        detected_format=detected_format,
    )


def scan_upload(
    *,
    filename: str,
    raw: bytes,
    text: str | None = None,
    block_threshold: float | None = None,
    flag_threshold: float | None = None,
) -> ScanReport:
    """Synchronous full scan (filename + bytes + optional text)."""
    block_threshold = BLOCK_SCORE if block_threshold is None else block_threshold
    flag_threshold = FLAG_SCORE if flag_threshold is None else flag_threshold

    findings: list[ScanFinding] = []
    findings.extend(scan_filename(filename))
    findings.extend(scan_raw_bytes(raw, filename))
    if text:
        findings.extend(scan_text_content(text))

    return _build_report(
        findings,
        filename=filename or "",
        detected_format=detect_format(raw),
        block_threshold=block_threshold,
        flag_threshold=flag_threshold,
    )


async def scan_upload_async(
    *,
    filename: str,
    raw: bytes,
    text: str | None = None,
    use_ai: bool | None = None,
    block_threshold: float | None = None,
    flag_threshold: float | None = None,
) -> ScanReport:
    """
    Async scan with optional AI boost when score is in the grey zone
    or SCAN_USE_AI is enabled.
    """
    report = scan_upload(
        filename=filename,
        raw=raw,
        text=text,
        block_threshold=block_threshold,
        flag_threshold=flag_threshold,
    )
    enable_ai = SCAN_USE_AI if use_ai is None else use_ai
    grey = FLAG_SCORE <= report.score < BLOCK_SCORE
    if not enable_ai or not (text or "").strip():
        return report
    if report.blocked and not grey:
        # already hard-blocked by rules; AI optional
        if report.score >= 0.95:
            return report

    try:
        from backend.core.telemetry import ai_threat_scan

        ai = await ai_threat_scan(text or "")
        ai_score = float(ai.get("score") or 0.0)
        if ai_score > report.score:
            report.findings.append(
                ScanFinding(
                    category=str((ai.get("hits") or [{}])[0].get("type") or "ai_threat"),
                    weight=ai_score,
                    evidence=_clip(str(ai.get("rationale") or ai.get("ai_label") or "ai")),
                    source="ai",
                )
            )
            return _build_report(
                report.findings,
                filename=report.filename,
                detected_format=report.detected_format,
                block_threshold=block_threshold or BLOCK_SCORE,
                flag_threshold=flag_threshold or FLAG_SCORE,
            )
    except Exception as exc:
        logger.warning("AI file scan skipped: %s", exc)

    return report
"""
Telemetry store + AI-assisted threat scoring + admin dashboard snapshots.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

Severity = Literal["low", "medium", "high", "critical"]

# Heuristic patterns (always on; no API key required)
_INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior)\s+instructions", "prompt_injection", 0.85),
    (r"system\s*prompt", "prompt_injection", 0.7),
    (r"jailbreak|dan\s*mode", "jailbreak", 0.8),
    (r"exfiltrat|data\s*leak", "data_exfil", 0.75),
    (r"https?://\d{1,3}(\.\d{1,3}){3}", "suspicious_ip_url", 0.55),
    (r"password\s*=\s*|api[_-]?key\s*=", "credential_harvest", 0.7),
    (r"<script|javascript:", "xss_payload", 0.65),
]


@dataclass
class ThreatEvent:
    timestamp: str
    threat_type: str
    source_ip: str = "—"
    severity: Severity = "low"
    confidence_score: float = 0.0
    detail: str | None = None
    document_id: str | None = None
    user_email: str | None = None
    detector: str = "heuristic"  # heuristic | ai | hybrid
    raw_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequestMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_processing_time_ms: float = 0.0
    endpoint_hits: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    status_code_counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))


def _score_to_severity(score: float) -> Severity:
    if score >= 0.9:
        return "critical"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def heuristic_threat_scan(text: str) -> dict[str, Any]:
    """Fast local detector — no network."""
    text_l = (text or "")[:20_000].lower()
    hits: list[dict[str, Any]] = []
    max_score = 0.0
    for pattern, ttype, weight in _INJECTION_PATTERNS:
        if re.search(pattern, text_l, re.I):
            hits.append({"type": ttype, "weight": weight})
            max_score = max(max_score, weight)
    # entropy-ish signal for obfuscation
    if len(text_l) > 200:
        unique = len(set(text_l))
        ratio = unique / max(len(text_l), 1)
        if ratio > 0.85:
            hits.append({"type": "high_entropy", "weight": 0.4})
            max_score = max(max_score, 0.4)
    return {
        "flagged": max_score >= 0.45,
        "score": round(max_score, 3),
        "severity": _score_to_severity(max_score),
        "hits": hits,
        "detector": "heuristic",
    }


async def ai_threat_scan(text: str) -> dict[str, Any]:
    """
    Optional LLM classifier. Falls back to heuristic-only if no OPENAI_API_KEY.
    Returns unified shape: flagged, score, severity, hits, detector, rationale.
    """
    base = heuristic_threat_scan(text)
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key or not (text or "").strip():
        return {**base, "rationale": None}

    def _call() -> dict[str, Any]:
        from openai import OpenAI
        import json

        client = OpenAI(api_key=api_key)
        model = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
        prompt = (
            "You are a security classifier for document and prompt content. "
            "Score risk of prompt injection, phishing, malware instructions, or data exfil. "
            "Reply ONLY JSON: "
            '{"score":0.0-1.0,"label":"clean|suspicious|malicious",'
            '"threat_types":["..."],"rationale":"short"}'
            f"\n\nCONTENT:\n{(text or '')[:6000]}"
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (resp.choices[0].message.content or "").strip()
        # strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
        return json.loads(raw)

    try:
        ai = await asyncio.to_thread(_call)
        ai_score = float(ai.get("score") or 0.0)
        # hybrid: max of heuristic and AI
        score = max(base["score"], ai_score)
        types = list(ai.get("threat_types") or [])
        for h in base.get("hits") or []:
            if h.get("type") and h["type"] not in types:
                types.append(h["type"])
        return {
            "flagged": score >= 0.45 or str(ai.get("label")) == "malicious",
            "score": round(score, 3),
            "severity": _score_to_severity(score),
            "hits": [{"type": t, "weight": score} for t in types] or base["hits"],
            "detector": "hybrid",
            "rationale": ai.get("rationale"),
            "ai_label": ai.get("label"),
        }
    except Exception as exc:
        logger.warning("AI threat scan failed: %s", exc)
        return {**base, "rationale": f"ai_unavailable: {exc}"}


class TelemetryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.metrics = RequestMetrics()
        settings = get_settings()
        self._events: deque[ThreatEvent] = deque(
            maxlen=max(50, settings.telemetry_retention_events)
        )
        self.total_caught = 0
        self.active_threats = 0
        self.scans_total = 0
        self.quarantine_total = 0
        self.ingest_success = 0
        self.ingest_failed = 0
        self.rag_queries = 0
        self.ai_scans_total = 0
        self.ai_flagged_total = 0
        self.severity_counts: dict[str, int] = defaultdict(int)

    def record_request(self, *, path: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            m = self.metrics
            m.total_requests += 1
            m.total_processing_time_ms += duration_ms
            m.status_code_counts[status_code] += 1
            m.endpoint_hits[path] += 1
            if status_code < 400:
                m.successful_requests += 1
            else:
                m.failed_requests += 1

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            m = self.metrics
            return {
                "total_requests": m.total_requests,
                "successful_requests": m.successful_requests,
                "failed_requests": m.failed_requests,
                "average_latency_ms": (
                    round(m.total_processing_time_ms / m.total_requests, 2)
                    if m.total_requests
                    else 0.0
                ),
                "endpoint_distribution": dict(m.endpoint_hits),
                "status_code_distribution": dict(m.status_code_counts),
                "uptime_seconds": round(time.time() - self.started_at, 2),
            }

    def record_threat(
        self,
        *,
        threat_type: str,
        severity: Severity = "medium",
        source_ip: str = "—",
        confidence_score: float = 0.0,
        detail: str | None = None,
        document_id: str | None = None,
        user_email: str | None = None,
        detector: str = "heuristic",
        raw_score: float | None = None,
        counted: bool = True,
    ) -> ThreatEvent:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        event = ThreatEvent(
            timestamp=ts,
            threat_type=threat_type,
            source_ip=source_ip or "—",
            severity=severity,
            confidence_score=float(confidence_score or 0.0),
            detail=detail,
            document_id=document_id,
            user_email=user_email,
            detector=detector,
            raw_score=raw_score,
        )
        with self._lock:
            self._events.appendleft(event)
            self.severity_counts[severity] += 1
            if counted:
                self.total_caught += 1
                if severity in ("high", "critical"):
                    self.active_threats += 1
        return event

    async def analyze_and_record(
        self,
        text: str,
        *,
        source_ip: str = "—",
        document_id: str | None = None,
        user_email: str | None = None,
        use_ai: bool = True,
    ) -> dict[str, Any]:
        """Run heuristic (+ optional AI), record if flagged, return full result."""
        result = await ai_threat_scan(text) if use_ai else heuristic_threat_scan(text)
        with self._lock:
            self.scans_total += 1
            self.ai_scans_total += 1 if result.get("detector") in ("hybrid", "ai") else 0

        if result.get("flagged"):
            hits = result.get("hits") or []
            ttype = hits[0]["type"] if hits else "suspicious_content"
            with self._lock:
                self.ai_flagged_total += 1
            self.record_threat(
                threat_type=str(ttype),
                severity=result.get("severity") or "medium",
                source_ip=source_ip,
                confidence_score=float(result.get("score") or 0),
                detail=result.get("rationale"),
                document_id=document_id,
                user_email=user_email,
                detector=str(result.get("detector") or "heuristic"),
                raw_score=float(result.get("score") or 0),
            )
        return result

    def record_scan(self, *, flagged: bool = False) -> None:
        with self._lock:
            self.scans_total += 1
            if flagged:
                self.total_caught += 1

    def record_quarantine(self) -> None:
        with self._lock:
            self.quarantine_total += 1
            self.active_threats += 1

    def record_ingest(self, *, success: bool) -> None:
        with self._lock:
            if success:
                self.ingest_success += 1
            else:
                self.ingest_failed += 1

    def record_rag_query(self) -> None:
        with self._lock:
            self.rag_queries += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            events = [e.to_dict() for e in list(self._events)[:100]]
            return {
                "total_caught": self.total_caught,
                "active_threats": self.active_threats,
                "scans_total": self.scans_total,
                "ai_scans_total": self.ai_scans_total,
                "ai_flagged_total": self.ai_flagged_total,
                "quarantine_total": self.quarantine_total,
                "ingest_success": self.ingest_success,
                "ingest_failed": self.ingest_failed,
                "rag_queries": self.rag_queries,
                "severity_counts": dict(self.severity_counts),
                "events": events,
            }

    def admin_dashboard(self) -> dict[str, Any]:
        """Combined snapshot for admin UI."""
        metrics = self.metrics_snapshot()
        summary = self.summary()
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "uptime_seconds": metrics["uptime_seconds"],
            "http": metrics,
            "threats": {
                "total_caught": summary["total_caught"],
                "active_threats": summary["active_threats"],
                "severity_counts": summary["severity_counts"],
                "ai_scans_total": summary["ai_scans_total"],
                "ai_flagged_total": summary["ai_flagged_total"],
            },
            "product": {
                "scans_total": summary["scans_total"],
                "quarantine_total": summary["quarantine_total"],
                "ingest_success": summary["ingest_success"],
                "ingest_failed": summary["ingest_failed"],
                "rag_queries": summary["rag_queries"],
            },
            "recent_events": summary["events"][:50],
        }

    def prometheus_lines(self) -> str:
        snap = self.metrics_snapshot()
        summary = self.summary()
        lines = [
            f'doc_intelligence_uptime_seconds {snap["uptime_seconds"]}',
            f'doc_intelligence_requests_total {snap["total_requests"]}',
            f'doc_intelligence_threats_total {summary["total_caught"]}',
            f'doc_intelligence_active_threats {summary["active_threats"]}',
            f'doc_intelligence_ai_scans_total {summary["ai_scans_total"]}',
            f'doc_intelligence_ai_flagged_total {summary["ai_flagged_total"]}',
            f'doc_intelligence_rag_queries_total {summary["rag_queries"]}',
        ]
        return "\n".join(lines) + "\n"


_store: TelemetryStore | None = None


def get_telemetry() -> TelemetryStore:
    global _store
    if _store is None:
        _store = TelemetryStore()
    return _store
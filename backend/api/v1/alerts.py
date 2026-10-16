"""
Alertmanager webhook receiver.

Receives alert notifications from Alertmanager, logs them, keeps a rolling
in-memory window for the demo UI, and exposes a Prometheus counter so alert
pipeline health is itself observable.

Wiring (main.py):
    try:
        from backend.api.v1.alerts import router as alerts_router
    except Exception:
        alerts_router = None
    if alerts_router is not None:
        app.include_router(alerts_router)

Alertmanager target (observability/alertmanager/alertmanager.yml):
    webhook_configs:
      - url: "http://backend:8000/api/v1/alerts/webhook"
        send_resolved: true
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, Request, status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])

# Soft-fail metrics handle (same pattern as main.py / rag_service).
try:
    from backend.observability import metrics as _metrics
except ImportError:  # pragma: no cover
    _metrics = None  # type: ignore[assignment]

# Rolling in-memory window of recent alerts (demo-friendly; cleared on restart).
_RECENT_ALERTS: deque[dict[str, Any]] = deque(maxlen=100)


def _record_received(alertname: str, severity: str, state: str) -> None:
    """Bump alerts_received_total{alertname,severity,state}."""
    if _metrics is not None and hasattr(_metrics, "ALERTS_RECEIVED"):
        counter = _metrics.ALERTS_RECEIVED
        if counter is not None:
            counter.labels(
                alertname=alertname or "unknown",
                severity=severity or "unknown",
                state=state or "unknown",
            ).inc()


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def receive_alertmanager_webhook(request: Request) -> dict[str, Any]:
    """
    Receive and process an Alertmanager webhook payload.

    Returns 200 even for malformed payloads (Alertmanager retries non-2xx
    forever, and a malformed payload will never succeed on retry).
    """
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("Alertmanager webhook: invalid JSON body: %s", exc)
        return {"status": "error", "detail": f"invalid JSON: {exc}"}

    if not isinstance(payload, dict):
        logger.error("Alertmanager webhook: payload is not an object")
        return {"status": "error", "detail": "payload must be a JSON object"}

    alerts = payload.get("alerts") or []
    if not isinstance(alerts, list):
        logger.error("Alertmanager webhook: 'alerts' is not a list")
        return {"status": "error", "detail": "'alerts' must be a list"}

    received_at = time.time()
    firing = resolved = 0

    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        state = str(alert.get("status") or "unknown")
        alertname = str(labels.get("alertname") or "UnknownAlert")
        severity = str(labels.get("severity") or "warning")
        summary = str(annotations.get("summary") or "")
        description = str(annotations.get("description") or "No description provided.")
        starts_at = alert.get("startsAt")
        fingerprint = str(alert.get("fingerprint") or "")

        entry = {
            "alertname": alertname,
            "severity": severity,
            "status": state,
            "summary": summary,
            "description": description,
            "starts_at": starts_at,
            "fingerprint": fingerprint,
            "received_at": received_at,
        }
        _RECENT_ALERTS.appendleft(entry)  # newest first
        _record_received(alertname, severity, state)

        if state == "firing":
            firing += 1
            log = logger.warning if severity != "critical" else logger.error
            log(
                "ALERT FIRING [%s] %s — %s | %s (starts_at=%s fp=%s)",
                severity.upper(),
                alertname,
                summary,
                description,
                starts_at,
                fingerprint,
            )
        elif state == "resolved":
            resolved += 1
            logger.info("ALERT RESOLVED %s (fp=%s)", alertname, fingerprint)
        else:
            logger.info("ALERT %s %s", state, alertname)

    logger.info(
        "Alertmanager webhook processed: %d alerts (%d firing, %d resolved)",
        len(alerts),
        firing,
        resolved,
    )
    return {
        "status": "success",
        "received_alerts_count": len(alerts),
        "firing": firing,
        "resolved": resolved,
    }
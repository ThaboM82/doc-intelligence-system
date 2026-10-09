"""
app/api/routes/security.py

REST API endpoints for document security, header authentication,
prompt injection scanning, and quarantining.

Router has NO prefix — main.py mounts at:
    app.include_router(security_router, prefix="/api/v1/security")

Final paths:
    POST /api/v1/security/verify-headers
    POST /api/v1/security/scan-prompt
    POST /api/v1/security/scan-document
    ...
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, Field

from app.database.vector_store import DocumentChunk, VectorStoreManager
from app.security.validators import (
    HeaderValidationResult,
    HeaderValidator,
    PromptInjectionDetector,
    PromptInjectionResult,
)

logger = logging.getLogger("document_intelligence_api.api.routes.security")

# IMPORTANT: no prefix here — main.py adds "/api/v1/security"
router = APIRouter(tags=["Security & Safeguards"])


# ==============================================================================
# Schemas
# ==============================================================================

class DocumentScanRequest(BaseModel):
    document_id: str = Field(..., description="Unique document identifier")
    text_content: str = Field(..., description="Extracted raw text content")
    index_vector: bool = Field(default=False)
    embedding: list[float] | None = Field(default=None)


class BatchDocumentScanRequest(BaseModel):
    documents: list[DocumentScanRequest] = Field(...)


class HeaderVerifyRequest(BaseModel):
    headers: dict[str, Any] = Field(..., description="Email authentication headers")


class ScanPromptRequest(BaseModel):
    text: str = Field(..., description="User or document text to scan")


class PipelineAuditReport(BaseModel):
    document_id: str
    is_safe: bool
    prompt_scan: PromptInjectionResult
    header_scan: HeaderValidationResult
    overall_risk_score: float
    recommended_action: str


class SystemHealthResponse(BaseModel):
    status: str
    validators_active: bool
    vector_store_status: dict[str, Any]


# ==============================================================================
# Dependencies
# ==============================================================================

def get_vector_store() -> VectorStoreManager:
    return VectorStoreManager()


# ==============================================================================
# Response mappers (API contract for test_security_api.py)
# ==============================================================================

def _header_api_response(report: Any) -> dict[str, Any]:
    findings = list(getattr(report, "findings", None) or [])
    # Exclude benign "all passed" lines from threats list
    threats = [
        f
        for f in findings
        if "passed" not in str(f).lower() and "all authentication" not in str(f).lower()
    ]
    suspicious = bool(getattr(report, "is_suspicious", False))
    risk = float(getattr(report, "risk_score", 0.0) or 0.0)
    return {
        "passed": not suspicious,
        "risk_score": risk,
        "threats_detected": threats,
        "details": {
            "spf_status": getattr(report, "spf_status", "none"),
            "dkim_status": getattr(report, "dkim_status", "none"),
            "dmarc_status": getattr(report, "dmarc_status", "none"),
            "dmarc_policy": getattr(report, "dmarc_policy", "none"),
            "arc_status": getattr(report, "arc_status", "none"),
            "domain_aligned": getattr(report, "domain_aligned", True),
            "from_domain": getattr(report, "from_domain", ""),
            "return_path_domain": getattr(report, "return_path_domain", ""),
            "findings": findings,
        },
    }


def _prompt_api_response(report: Any) -> dict[str, Any]:
    patterns = list(getattr(report, "matched_patterns", None) or [])
    anomalies = list(getattr(report, "detected_anomalies", None) or [])
    threats = patterns if patterns else anomalies
    flagged = bool(getattr(report, "is_flagged", False))
    risk = float(getattr(report, "risk_score", 0.0) or 0.0)
    return {
        "passed": not flagged,
        "risk_score": risk,
        "threats_detected": threats,
        "details": {
            "severity": getattr(report, "severity", "clean"),
            "matched_patterns": patterns,
            "detected_anomalies": anomalies,
            "threat_categories": list(getattr(report, "threat_categories", None) or []),
            "entropy_score": getattr(report, "entropy_score", 0.0),
        },
    }


def _document_api_response(
    *,
    filename: str,
    injection: Any,
    header_report: Any = None,
) -> dict[str, Any]:
    inj = _prompt_api_response(injection) if injection is not None else {
        "passed": True,
        "risk_score": 0.0,
        "threats_detected": [],
        "details": {},
    }
    threats = list(inj.get("threats_detected") or [])
    flagged = not inj.get("passed", True)
    risk = float(inj.get("risk_score") or 0.0)

    if header_report is not None:
        hdr = _header_api_response(header_report)
        if not hdr.get("passed", True):
            flagged = True
        risk = max(risk, float(hdr.get("risk_score") or 0.0))
        threats = threats + list(hdr.get("threats_detected") or [])

    return {
        "filename": filename,
        "is_flagged": flagged,
        "status": "quarantined" if flagged else "verified_safe",
        "threats_detected": threats,
        "risk_score": risk,
        "injection": inj,
        "headers": _header_api_response(header_report) if header_report is not None else None,
    }


# ==============================================================================
# Endpoints
# ==============================================================================

@router.get("/health", response_model=SystemHealthResponse, status_code=status.HTTP_200_OK)
async def check_security_health(
    vector_store: VectorStoreManager = Depends(get_vector_store),
):
    vs_stats = vector_store.get_collection_stats()
    return SystemHealthResponse(
        status="ok" if vs_stats.get("status") in ("online", "offline") else "degraded",
        validators_active=True,
        vector_store_status=vs_stats,
    )


@router.post("/verify-headers", status_code=status.HTTP_200_OK)
async def verify_email_headers(payload: HeaderVerifyRequest):
    """
    SPF / DKIM / DMARC / alignment check.
    Response contract: { passed, risk_score, threats_detected, details }
    """
    if not payload.headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Headers dictionary cannot be empty.",
        )
    try:
        report = HeaderValidator.verify_spf_dkim_dmarc(payload.headers)
        return _header_api_response(report)
    except Exception as exc:
        logger.warning("verify-headers failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse or validate email headers: {exc}",
        ) from exc


@router.post("/scan-prompt", status_code=status.HTTP_200_OK)
async def scan_prompt(payload: ScanPromptRequest):
    """
    Free-text prompt injection scan.
    Response contract: { passed, risk_score, threats_detected, details }
    """
    try:
        report = PromptInjectionDetector.scan_text(payload.text)
        return _prompt_api_response(report)
    except Exception as exc:
        logger.exception("scan-prompt failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing security scan: {exc}",
        ) from exc


@router.post("/scan-document", status_code=status.HTTP_200_OK)
async def scan_document(
    request: Request,
    vector_store: VectorStoreManager = Depends(get_vector_store),
):
    """
    Supports:
      - multipart/form-data → file + optional headers_json  (test_security_api)
      - application/json    → DocumentScanRequest           (test_security_routes)
    """
    content_type = (request.headers.get("content-type") or "").lower()

    # ----- multipart upload -----
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="file is required",
            )

        raw = await upload.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""

        headers: dict[str, Any] = {}
        headers_json = form.get("headers_json")
        if headers_json is not None and str(headers_json).strip():
            try:
                headers = json.loads(str(headers_json))
                if not isinstance(headers, dict):
                    raise ValueError("headers_json must be a JSON object")
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid JSON string in headers_json: {exc}",
                ) from exc

        try:
            injection = PromptInjectionDetector.scan_text(text)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error executing security scan: {exc}",
            ) from exc

        header_report = None
        if headers:
            try:
                header_report = HeaderValidator.verify_spf_dkim_dmarc(headers)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to parse or validate email headers: {exc}",
                ) from exc

        filename = getattr(upload, "filename", None) or "upload"
        return _document_api_response(
            filename=filename,
            injection=injection,
            header_report=header_report,
        )

    # ----- JSON body (routes tests) -----
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON body: {exc}",
        ) from exc

    try:
        payload = DocumentScanRequest(**body)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not payload.text_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document text content cannot be empty.",
        )

    scan_result = PromptInjectionDetector.scan_text(payload.text_content)

    if payload.index_vector and payload.embedding:
        chunk = DocumentChunk(
            chunk_id=f"{payload.document_id}_0",
            document_id=payload.document_id,
            content=payload.text_content,
            embedding=payload.embedding,
            security_flagged=scan_result.is_flagged,
            risk_score=scan_result.risk_score,
            metadata={
                "matched_patterns": scan_result.matched_patterns,
                "anomalies": scan_result.detected_anomalies,
            },
        )
        vector_store.upsert_chunks([chunk])

    # Routes tests expect PromptInjectionResult shape (model fields)
    return scan_result


@router.post(
    "/scan-batch",
    response_model=list[PromptInjectionResult],
    status_code=status.HTTP_200_OK,
)
async def scan_document_batch(payload: BatchDocumentScanRequest):
    if not payload.documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document list cannot be empty.",
        )
    results: list[PromptInjectionResult] = []
    for doc in payload.documents:
        if not doc.text_content.strip():
            continue
        results.append(PromptInjectionDetector.scan_text(doc.text_content))
    return results


@router.post("/audit-pipeline", response_model=PipelineAuditReport, status_code=status.HTTP_200_OK)
async def audit_document_pipeline(
    document_id: str,
    text_content: str,
    headers: dict[str, str] | None = None,
):
    prompt_res = PromptInjectionDetector.scan_text(text_content or "")
    header_res = HeaderValidator.verify_spf_dkim_dmarc(headers or {})
    overall_risk = round(max(prompt_res.risk_score, header_res.risk_score), 2)
    is_safe = not prompt_res.is_flagged and not header_res.is_suspicious

    if overall_risk >= 0.70:
        recommended_action = "QUARANTINE"
    elif overall_risk >= 0.35:
        recommended_action = "FLAG_FOR_REVIEW"
    else:
        recommended_action = "ALLOW"

    return PipelineAuditReport(
        document_id=document_id,
        is_safe=is_safe,
        prompt_scan=prompt_res,
        header_scan=header_res,
        overall_risk_score=overall_risk,
        recommended_action=recommended_action,
    )


@router.delete("/quarantine/{document_id}", status_code=status.HTTP_200_OK)
async def quarantine_document(
    document_id: str,
    vector_store: VectorStoreManager = Depends(get_vector_store),
):
    success = vector_store.delete_document_vectors(document_id)
    if not success:
        logger.warning("Failed to purge vectors for document_id '%s'.", document_id)
        return {
            "document_id": document_id,
            "status": "failed",
            "message": "Could not purge vector chunks.",
        }
    return {
        "document_id": document_id,
        "status": "quarantined",
        "message": "All vector chunks purged successfully.",
    }
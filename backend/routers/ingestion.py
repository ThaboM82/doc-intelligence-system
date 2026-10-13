"""
Document ingestion API — upload, delete vectors, lightweight status.

Routes:
  POST   /api/v1/documents/upload
  DELETE /api/v1/documents/{document_id}
  GET    /api/v1/documents/health
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.ingest_service import (
    delete_document_vectors,
    ingest_bytes,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Document Management"])

MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
ALLOWED_EXT = {
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
ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/octet-stream",  # browsers often send this
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    security_scan_passed: bool
    message: str
    chunks_upserted: int = 0
    warnings: list[str] = Field(default_factory=list)
    char_count: int = 0
    processing_time_ms: float = 0.0
    collection: str | None = None


class DeleteResponse(BaseModel):
    status: str
    document_id: str
    message: str


class IngestHealthResponse(BaseModel):
    ok: bool
    max_upload_bytes: int
    allowed_extensions: list[str]
    collection: str
    detail: str = "ingestion router ready"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="File must have an extension (e.g. .pdf, .txt).",
        )
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXT)}",
        )
    return ext


def _validate_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    base = content_type.split(";")[0].strip().lower()
    if base and base not in ALLOWED_CONTENT_TYPES:
        # Soft warn only — extension is source of truth (browsers lie)
        logger.info("Unusual content-type for upload: %s", content_type)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/documents/health",
    response_model=IngestHealthResponse,
    summary="Ingestion module health",
)
async def ingestion_health() -> IngestHealthResponse:
    collection = os.getenv("QDRANT_COLLECTION") or os.getenv(
        "QDRANT_COLLECTION_NAME", "document_intelligence"
    )
    return IngestHealthResponse(
        ok=True,
        max_upload_bytes=MAX_BYTES,
        allowed_extensions=sorted(ALLOWED_EXT),
        collection=collection,
    )


@router.post(
    "/api/v1/documents/upload",
    response_model=UploadResponse,
    summary="Upload and index a document into Qdrant",
)
async def upload_document(
    file: UploadFile = File(..., description="Document to ingest"),
    skip_security: bool = Form(False),
    department: str | None = Form(None),
    tags: str | None = Form(None, description="Comma-separated tags"),
) -> JSONResponse:
    filename = file.filename or "upload.bin"
    _validate_extension(filename)
    _validate_content_type(file.content_type)

    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_BYTES} bytes (got {len(raw)}).",
        )

    metadata: dict[str, Any] = {}
    if department:
        metadata["department"] = department.strip()
    if tags:
        metadata["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    try:
        result = await ingest_bytes(
            filename,
            raw,
            skip_security=bool(skip_security),
            metadata=metadata or None,
        )
    except Exception as exc:
        logger.exception("upload failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingest failed: {exc}",
        ) from exc

    body = UploadResponse(
        document_id=result.document_id,
        filename=result.filename,
        status=result.status,
        security_scan_passed=result.security_scan_passed,
        message=result.message,
        chunks_upserted=result.chunks_upserted,
        warnings=result.warnings,
        char_count=getattr(result, "char_count", 0) or 0,
        processing_time_ms=getattr(result, "processing_time_ms", 0.0) or 0.0,
        collection=getattr(result, "collection", None),
    )

    if result.status == "failed":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": result.message,
                "document_id": result.document_id,
                "warnings": result.warnings,
            },
        )

    # quarantined → 200; indexed → 201
    http_status = (
        status.HTTP_200_OK
        if result.status == "quarantined"
        else status.HTTP_201_CREATED
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


@router.delete(
    "/api/v1/documents/{document_id}",
    response_model=DeleteResponse,
    summary="Delete all vector chunks for a document_id",
)
async def delete_document(document_id: str) -> DeleteResponse:
    document_id = (document_id or "").strip()
    if not document_id or len(document_id) > 80:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid document_id.")

    try:
        await delete_document_vectors(document_id)
    except Exception as exc:
        logger.exception("delete vectors failed for %s", document_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not delete vectors: {exc}",
        ) from exc

    return DeleteResponse(
        status="success",
        document_id=document_id,
        message=f"Delete requested for document {document_id} vectors.",
    )
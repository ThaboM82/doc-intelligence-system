"""
Document ingestion API — upload, health, and optional re-ingest helpers.

Routes (this module):
  POST  /api/v1/documents/upload
  GET   /api/v1/documents/health
  GET   /api/v1/documents/ingest/config

List / get / delete (backend.routers.documents):
  GET    /api/v1/documents
  GET    /api/v1/documents/{document_id}
  DELETE /api/v1/documents/{document_id}
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.ingest_service import ingest_bytes

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
    "application/octet-stream",
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
    request_id: str | None = None


class IngestHealthResponse(BaseModel):
    ok: bool
    max_upload_bytes: int
    allowed_extensions: list[str]
    allowed_content_types: list[str]
    collection: str
    detail: str = "ingestion router ready"
    upload_path: str = "/api/v1/documents/upload"


class IngestConfigResponse(BaseModel):
    max_upload_bytes: int
    chunk_size: int
    chunk_overlap: int
    max_ingest_chars: int
    collection: str
    allowed_extensions: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collection_name() -> str:
    return os.getenv("QDRANT_COLLECTION") or os.getenv(
        "QDRANT_COLLECTION_NAME", "document_intelligence"
    )


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
        # Extension is source of truth — browsers often send octet-stream
        logger.info("Unusual content-type for upload: %s", content_type)


def _request_id(request: Request | None, header_val: str | None) -> str | None:
    if header_val:
        return header_val.strip()[:64]
    if request is not None:
        return getattr(request.state, "request_id", None)
    return None


def _parse_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [t.strip() for t in tags.split(",") if t.strip()][:20]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/documents/health",
    response_model=IngestHealthResponse,
    summary="Ingestion module health",
)
async def ingestion_health() -> IngestHealthResponse:
    return IngestHealthResponse(
        ok=True,
        max_upload_bytes=MAX_BYTES,
        allowed_extensions=sorted(ALLOWED_EXT),
        allowed_content_types=sorted(ALLOWED_CONTENT_TYPES),
        collection=_collection_name(),
    )


@router.get(
    "/api/v1/documents/ingest/config",
    response_model=IngestConfigResponse,
    summary="Ingestion configuration (chunk sizes, limits)",
)
async def ingestion_config() -> IngestConfigResponse:
    return IngestConfigResponse(
        max_upload_bytes=MAX_BYTES,
        chunk_size=int(os.getenv("INGEST_CHUNK_SIZE", "800")),
        chunk_overlap=int(os.getenv("INGEST_CHUNK_OVERLAP", "120")),
        max_ingest_chars=int(os.getenv("MAX_INGEST_CHARS", "500000")),
        collection=_collection_name(),
        allowed_extensions=sorted(ALLOWED_EXT),
    )


@router.post(
    "/api/v1/documents/upload",
    response_model=UploadResponse,
    summary="Upload and index a document into Qdrant",
)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="Document to ingest"),
    skip_security: bool = Form(False),
    department: str | None = Form(None),
    tags: str | None = Form(None, description="Comma-separated tags"),
    title: str | None = Form(None, description="Optional display title"),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
) -> JSONResponse:
    """
    Multipart upload → security scan → extract → chunk → embed → Qdrant.

    Status codes:
      201 — indexed
      200 — quarantined (not indexed)
      422 — failed (no text / indexing error)
      413 — too large
      400 — bad extension / empty
    """
    t0 = time.perf_counter()
    rid = _request_id(request, x_request_id)
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
        metadata["department"] = department.strip()[:120]
    tag_list = _parse_tags(tags)
    if tag_list:
        metadata["tags"] = tag_list
    if title:
        metadata["title"] = title.strip()[:240]
    if rid:
        metadata["request_id"] = rid

    logger.info(
        "ingest upload start file=%s bytes=%s ctype=%s skip_security=%s rid=%s",
        filename,
        len(raw),
        file.content_type,
        skip_security,
        rid,
    )

    try:
        result = await ingest_bytes(
            filename,
            raw,
            skip_security=bool(skip_security),
            metadata=metadata or None,
        )
    except Exception as exc:
        logger.exception("upload failed rid=%s", rid)
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
        warnings=list(result.warnings or []),
        char_count=getattr(result, "char_count", 0) or 0,
        processing_time_ms=getattr(result, "processing_time_ms", 0.0)
        or round((time.perf_counter() - t0) * 1000, 2),
        collection=getattr(result, "collection", None) or _collection_name(),
        request_id=rid,
    )

    logger.info(
        "ingest upload done status=%s doc_id=%s chunks=%s ms=%.1f rid=%s",
        result.status,
        result.document_id,
        result.chunks_upserted,
        body.processing_time_ms,
        rid,
    )

    if result.status == "failed":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": result.message,
                "document_id": result.document_id,
                "warnings": result.warnings,
                "request_id": rid,
            },
        )

    http_status = (
        status.HTTP_200_OK
        if result.status == "quarantined"
        else status.HTTP_201_CREATED
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())
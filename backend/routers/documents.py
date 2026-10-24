"""
Document management API — list / get / upload / delete ingested docs in Qdrant.

Routes:
  GET    /api/v1/documents
  POST   /api/v1/documents/upload
  GET    /api/v1/documents/{document_id}
  DELETE /api/v1/documents/{document_id}

Compatible with frontend DocumentManager + DocumentUpload + apiClient.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["Document Management"])

COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
SCROLL_BATCH = int(os.getenv("DOCUMENTS_SCROLL_BATCH", "256"))
SCROLL_MAX_POINTS = int(os.getenv("DOCUMENTS_SCROLL_MAX", "5000"))
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
    ".xlsx",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DocumentSummary(BaseModel):
    id: str
    document_id: str
    filename: str
    text_snippet: str = ""
    status: str = "indexed"
    chunks: int = 0
    chunks_upserted: int = 0
    security_scan_passed: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    uploaded_at: float | str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
    total: int
    offset: int = 0
    limit: int = 50
    collection: str = COLLECTION


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
    points_deleted: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _payload_doc_id(payload: dict[str, Any], point_id: Any = "") -> str:
    for key in ("document_id", "doc_id"):
        val = payload.get(key)
        if val:
            return str(val)
    chunk_id = payload.get("chunk_id")
    if isinstance(chunk_id, str) and ":" in chunk_id:
        return chunk_id.rsplit(":", 1)[0]
    return str(point_id) if point_id else ""


def _payload_filename(payload: dict[str, Any]) -> str:
    for key in ("filename", "file_name", "source_file", "title"):
        val = payload.get(key)
        if val:
            return str(val)
    return "unknown"


def _snippet(payload: dict[str, Any], max_len: int = 180) -> str:
    text = (
        payload.get("text")
        or payload.get("content")
        or payload.get("chunk_text")
        or ""
    )
    text = str(text).strip().replace("\n", " ")
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


async def _get_client():
    from backend.db.qdrant import get_qdrant_client

    return await get_qdrant_client()


async def _scroll_all_points(
    *,
    document_id: str | None = None,
) -> list[Any]:
    """Scroll points (optionally filtered by document_id). Caps at SCROLL_MAX_POINTS."""
    from qdrant_client.http import models as qm

    client = await _get_client()
    qfilter = None
    if document_id:
        qfilter = qm.Filter(
            should=[
                qm.FieldCondition(
                    key="document_id",
                    match=qm.MatchValue(value=document_id),
                ),
                qm.FieldCondition(
                    key="doc_id",
                    match=qm.MatchValue(value=document_id),
                ),
            ]
        )

    points: list[Any] = []
    offset: Any = None
    while len(points) < SCROLL_MAX_POINTS:
        try:
            batch, next_offset = await client.scroll(
                collection_name=COLLECTION,
                scroll_filter=qfilter,
                limit=min(SCROLL_BATCH, SCROLL_MAX_POINTS - len(points)),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.exception("Qdrant scroll failed")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Vector store unavailable: {exc}",
            ) from exc

        points.extend(batch or [])
        if next_offset is None or not batch:
            break
        offset = next_offset

    return points


def _group_documents(points: list[Any]) -> list[DocumentSummary]:
    groups: dict[str, dict[str, Any]] = {}

    for p in points:
        payload = getattr(p, "payload", None) or {}
        if not isinstance(payload, dict):
            payload = {}
        doc_id = _payload_doc_id(payload, getattr(p, "id", ""))
        if not doc_id:
            continue

        g = groups.get(doc_id)
        if g is None:
            uploaded = payload.get("uploaded_at") or payload.get("ingested_at")
            sec = payload.get("security_scan_passed")
            if sec is not None:
                sec = bool(sec)
            groups[doc_id] = {
                "id": doc_id,
                "document_id": doc_id,
                "filename": _payload_filename(payload),
                "text_snippet": _snippet(payload),
                "status": str(payload.get("status") or "indexed"),
                "chunks": 1,
                "security_scan_passed": sec,
                "uploaded_at": uploaded,
                "metadata": {
                    k: v
                    for k, v in payload.items()
                    if k
                    not in {
                        "text",
                        "content",
                        "chunk_text",
                        "document_id",
                        "doc_id",
                        "chunk_id",
                        "chunk_index",
                        "vector",
                    }
                },
            }
        else:
            g["chunks"] += 1
            if not g.get("text_snippet"):
                g["text_snippet"] = _snippet(payload)
            if not g.get("filename") or g["filename"] == "unknown":
                g["filename"] = _payload_filename(payload)
            if g.get("uploaded_at") is None:
                g["uploaded_at"] = payload.get("uploaded_at") or payload.get(
                    "ingested_at"
                )
            if g.get("security_scan_passed") is None and payload.get(
                "security_scan_passed"
            ) is not None:
                g["security_scan_passed"] = bool(
                    payload.get("security_scan_passed")
                )

    docs: list[DocumentSummary] = []
    for g in groups.values():
        n = int(g.get("chunks") or 0)
        docs.append(
            DocumentSummary(
                id=str(g["id"]),
                document_id=str(g["document_id"]),
                filename=str(g.get("filename") or "unknown"),
                text_snippet=str(g.get("text_snippet") or ""),
                status=str(g.get("status") or "indexed"),
                chunks=n,
                chunks_upserted=n,
                security_scan_passed=g.get("security_scan_passed"),
                metadata=dict(g.get("metadata") or {}),
                uploaded_at=g.get("uploaded_at"),
            )
        )

    def sort_key(d: DocumentSummary) -> float:
        u = d.uploaded_at
        if isinstance(u, (int, float)):
            return float(u)
        try:
            return float(u)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    docs.sort(key=sort_key, reverse=True)
    return docs


# ---------------------------------------------------------------------------
# Routes — static paths before /{document_id}
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List ingested documents (grouped by document_id)",
)
async def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Search filename or snippet"),
    status_filter: str | None = Query(None, alias="status"),
    security_passed: bool | None = Query(
        None, description="Filter by security_scan_passed"
    ),
) -> DocumentListResponse:
    points = await _scroll_all_points()
    docs = _group_documents(points)

    if status_filter:
        sf = status_filter.strip().lower()
        docs = [d for d in docs if d.status.lower() == sf]

    if security_passed is not None:
        docs = [
            d
            for d in docs
            if d.security_scan_passed is not None
            and bool(d.security_scan_passed) is security_passed
        ]

    if q:
        needle = q.strip().lower()
        docs = [
            d
            for d in docs
            if needle in d.filename.lower()
            or needle in d.text_snippet.lower()
            or needle in d.document_id.lower()
        ]

    total = len(docs)
    page = docs[offset : offset + limit]
    return DocumentListResponse(
        documents=page,
        total=total,
        offset=offset,
        limit=limit,
        collection=COLLECTION,
    )


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a document into Qdrant",
)
async def upload_document(file: UploadFile = File(...)) -> JSONResponse:
    """
    Multipart upload → security scan → extract → chunk → embed → upsert.
    Status: indexed (201), quarantined (200), failed (422).
    """
    filename = file.filename or "upload.bin"
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in ALLOWED_EXT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {sorted(ALLOWED_EXT)}"
            ),
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_BYTES} bytes.",
        )

    try:
        from backend.services.ingest_service import ingest_bytes

        result = await ingest_bytes(filename, raw)
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
        chunks_upserted=getattr(result, "chunks_upserted", 0) or 0,
        warnings=list(getattr(result, "warnings", None) or []),
        char_count=getattr(result, "char_count", 0) or 0,
        processing_time_ms=float(
            getattr(result, "processing_time_ms", 0.0) or 0.0
        ),
        collection=getattr(result, "collection", None) or COLLECTION,
    )

    if result.status == "failed":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": result.message,
                "document_id": result.document_id,
                "warnings": body.warnings,
            },
        )

    http_status = (
        status.HTTP_200_OK
        if result.status == "quarantined"
        else status.HTTP_201_CREATED
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


@router.get(
    "/{document_id}",
    response_model=DocumentSummary,
    summary="Get one document summary by document_id",
)
async def get_document(document_id: str) -> DocumentSummary:
    document_id = (document_id or "").strip()
    if not document_id or len(document_id) > 80:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Invalid document_id."
        )

    points = await _scroll_all_points(document_id=document_id)
    docs = _group_documents(points)
    if not docs:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found in vector store",
        )
    return docs[0]


@router.delete(
    "/{document_id}",
    response_model=DeleteResponse,
    summary="Delete all vector chunks for a document_id",
)
async def delete_document(document_id: str) -> DeleteResponse:
    document_id = (document_id or "").strip()
    if not document_id or len(document_id) > 80:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Invalid document_id."
        )

    from qdrant_client.http import models as qm

    client = await _get_client()
    points_deleted = 0
    filename: str | None = None

    try:
        existing = await _scroll_all_points(document_id=document_id)
        if existing:
            payload = getattr(existing[0], "payload", None) or {}
            if isinstance(payload, dict):
                filename = _payload_filename(payload)
            points_deleted = len(existing)
    except Exception:
        pass

    deleted_via_filter = False
    for key in ("document_id", "doc_id"):
        try:
            await client.delete(
                collection_name=COLLECTION,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[
                            qm.FieldCondition(
                                key=key,
                                match=qm.MatchValue(value=document_id),
                            )
                        ]
                    )
                ),
            )
            deleted_via_filter = True
            break
        except Exception as filter_exc:
            logger.debug(
                "Filter delete with key=%s failed: %s", key, filter_exc
            )
            continue

    if not deleted_via_filter:
        points = await _scroll_all_points(document_id=document_id)
        ids: list[Any] = [
            getattr(p, "id") for p in points if getattr(p, "id", None)
        ]
        if not ids:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found in vector store",
            )
        try:
            await client.delete(
                collection_name=COLLECTION,
                points_selector=qm.PointIdsList(points=ids),
            )
            points_deleted = len(ids)
        except Exception as exc:
            logger.exception("delete document failed")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Delete failed: {exc}",
            ) from exc

    try:
        from backend.security.event_publish import emit_document_deleted

        emit_document_deleted(
            document_id=document_id,
            filename=filename,
            points_deleted=points_deleted or None,
        )
    except Exception:
        logger.debug("emit_document_deleted failed", exc_info=True)

    try:
        from backend.services.ingest_service import delete_document_vectors

        await delete_document_vectors(document_id)
    except Exception:
        pass

    return DeleteResponse(
        status="deleted",
        document_id=document_id,
        points_deleted=max(points_deleted, 0),
        message=f"Removed vector points for document_id={document_id}",
    )
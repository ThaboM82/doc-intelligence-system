"""
Document management API — list / get / delete ingested docs in Qdrant.

Routes:
  GET    /api/v1/documents
  GET    /api/v1/documents/{document_id}
  DELETE /api/v1/documents/{document_id}

Query params (list):
  q              — search filename / snippet / id
  limit          — page size (1–500, default 50)
  offset         — skip N documents (default 0)
  status         — filter status (indexed, quarantined, …)
  department     — payload metadata.department
  tag            — tag must be in payload tags list
  security       — "passed" | "failed" | "unknown"
  sort           — uploaded_at | filename | chunks  (default uploaded_at)
  order          — desc | asc (default desc)

Compatible with frontend DocumentManager + apiClient.deleteDocument.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["Document Management"])

COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
SCROLL_PAGE = int(os.getenv("DOCUMENTS_SCROLL_PAGE", "100"))
SCROLL_MAX = int(os.getenv("DOCUMENTS_SCROLL_MAX", "5000"))


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
    tags: list[str] = Field(default_factory=list)
    department: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
    total: int
    limit: int
    offset: int
    has_more: bool = False
    collection: str = COLLECTION
    filters_applied: dict[str, Any] = Field(default_factory=dict)


class DeleteResponse(BaseModel):
    status: str
    document_id: str
    points_deleted: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


async def _client():
    from backend.db.qdrant import get_qdrant_client

    return await get_qdrant_client()


def _payload_doc_id(payload: dict[str, Any], point_id: Any) -> str:
    for key in ("document_id", "doc_id", "source_id"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val)
    return str(point_id)


def _payload_filename(payload: dict[str, Any]) -> str:
    for key in ("filename", "file_name", "source_file", "title", "source"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val)
    return "document"


def _payload_text(payload: dict[str, Any]) -> str:
    for key in ("text", "content", "chunk_text", "snippet"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _payload_tags(payload: dict[str, Any]) -> list[str]:
    tags = payload.get("tags")
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    if isinstance(tags, str) and tags.strip():
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


async def _scroll_all_points(
    limit_per_page: int = SCROLL_PAGE,
    max_points: int = SCROLL_MAX,
) -> list[Any]:
    """Scroll collection points (payload only). Caps at max_points."""
    client = await _client()
    points: list[Any] = []
    next_offset: Any = None

    while len(points) < max_points:
        kwargs: dict[str, Any] = {
            "collection_name": COLLECTION,
            "limit": min(limit_per_page, max_points - len(points)),
            "with_payload": True,
            "with_vectors": False,
        }
        if next_offset is not None:
            kwargs["offset"] = next_offset

        try:
            result = await client.scroll(**kwargs)
        except Exception as exc:
            logger.exception("Qdrant scroll failed")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Qdrant scroll failed: {exc}",
            ) from exc

        batch = (
            result[0]
            if isinstance(result, tuple)
            else getattr(result, "points", result)
        )
        batch = list(batch or [])
        points.extend(batch)

        next_offset = (
            result[1]
            if isinstance(result, tuple)
            else getattr(result, "next_page_offset", None)
        )
        if not batch or next_offset is None:
            break

    return points


def _group_documents(points: list[Any]) -> list[DocumentSummary]:
    groups: dict[str, dict[str, Any]] = {}

    for p in points:
        payload = getattr(p, "payload", None) or {}
        if not isinstance(payload, dict):
            payload = {}
        pid = getattr(p, "id", None)
        doc_id = _payload_doc_id(payload, pid)
        text = _payload_text(payload)
        filename = _payload_filename(payload)
        tags = _payload_tags(payload)
        department = payload.get("department")
        if department is not None:
            department = str(department)

        if doc_id not in groups:
            meta = {
                k: payload.get(k)
                for k in (
                    "source",
                    "department",
                    "page",
                    "mime_type",
                    "title",
                    "request_id",
                )
                if payload.get(k) is not None
            }
            if tags:
                meta["tags"] = tags
            groups[doc_id] = {
                "id": doc_id,
                "document_id": doc_id,
                "filename": filename,
                "text_snippet": text[:240],
                "status": str(payload.get("status") or "indexed"),
                "chunks": 0,
                "security_scan_passed": payload.get("security_scan_passed"),
                "metadata": meta,
                "uploaded_at": payload.get("uploaded_at")
                or payload.get("created_at")
                or payload.get("ingested_at"),
                "tags": tags,
                "department": department,
            }

        groups[doc_id]["chunks"] += 1
        if len(text) > len(groups[doc_id].get("text_snippet") or ""):
            groups[doc_id]["text_snippet"] = text[:240]
        if filename and groups[doc_id]["filename"] == "document":
            groups[doc_id]["filename"] = filename
        # merge tags
        existing = set(groups[doc_id].get("tags") or [])
        existing.update(tags)
        groups[doc_id]["tags"] = sorted(existing)

    out: list[DocumentSummary] = []
    for g in groups.values():
        n = int(g["chunks"])
        out.append(
            DocumentSummary(
                id=g["id"],
                document_id=g["document_id"],
                filename=g["filename"],
                text_snippet=g.get("text_snippet") or "",
                status=g.get("status") or "indexed",
                chunks=n,
                chunks_upserted=n,
                security_scan_passed=g.get("security_scan_passed"),
                metadata=g.get("metadata") or {},
                uploaded_at=g.get("uploaded_at"),
                tags=list(g.get("tags") or []),
                department=g.get("department"),
            )
        )
    return out


def _sort_key_uploaded(d: DocumentSummary) -> float:
    u = d.uploaded_at
    try:
        return float(u) if u is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _apply_filters(
    docs: list[DocumentSummary],
    *,
    q: str | None,
    status_filter: str | None,
    department: str | None,
    tag: str | None,
    security: str | None,
) -> list[DocumentSummary]:
    result = docs

    if q and q.strip():
        needle = q.strip().lower()
        result = [
            d
            for d in result
            if needle in d.filename.lower()
            or needle in (d.text_snippet or "").lower()
            or needle in d.document_id.lower()
            or any(needle in t.lower() for t in d.tags)
        ]

    if status_filter and status_filter.strip():
        st = status_filter.strip().lower()
        result = [d for d in result if (d.status or "").lower() == st]

    if department and department.strip():
        dep = department.strip().lower()
        result = [
            d
            for d in result
            if (d.department or "").lower() == dep
            or str((d.metadata or {}).get("department") or "").lower() == dep
        ]

    if tag and tag.strip():
        tneedle = tag.strip().lower()
        result = [
            d
            for d in result
            if any(tneedle == t.lower() or tneedle in t.lower() for t in d.tags)
        ]

    if security:
        sec = security.strip().lower()
        if sec == "passed":
            result = [d for d in result if d.security_scan_passed is True]
        elif sec == "failed":
            result = [d for d in result if d.security_scan_passed is False]
        elif sec == "unknown":
            result = [d for d in result if d.security_scan_passed is None]

    return result


def _sort_docs(
    docs: list[DocumentSummary],
    sort: str,
    order: str,
) -> list[DocumentSummary]:
    reverse = order.lower() != "asc"
    if sort == "filename":
        return sorted(docs, key=lambda d: (d.filename or "").lower(), reverse=reverse)
    if sort == "chunks":
        return sorted(docs, key=lambda d: d.chunks or 0, reverse=reverse)
    # default uploaded_at
    return sorted(docs, key=_sort_key_uploaded, reverse=reverse)


async def _count_points_for_doc(document_id: str) -> int:
    """Best-effort count before delete."""
    points = await _scroll_all_points()
    n = 0
    for p in points:
        payload = getattr(p, "payload", None) or {}
        if not isinstance(payload, dict):
            continue
        if _payload_doc_id(payload, getattr(p, "id", "")) == document_id:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=DocumentListResponse)
@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    q: str | None = Query(None, description="Search filename, snippet, id, tags"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Skip N documents"),
    status_filter: str | None = Query(
        None, alias="status", description="Filter by status"
    ),
    department: str | None = Query(None, description="Filter by department metadata"),
    tag: str | None = Query(None, description="Filter by tag"),
    security: Literal["passed", "failed", "unknown"] | None = Query(
        None, description="Filter by security_scan_passed"
    ),
    sort: Literal["uploaded_at", "filename", "chunks"] = Query("uploaded_at"),
    order: Literal["asc", "desc"] = Query("desc"),
) -> DocumentListResponse:
    points = await _scroll_all_points()
    docs = _group_documents(points)
    docs = _apply_filters(
        docs,
        q=q,
        status_filter=status_filter,
        department=department,
        tag=tag,
        security=security,
    )
    docs = _sort_docs(docs, sort=sort, order=order)

    total = len(docs)
    page = docs[offset : offset + limit]
    filters_applied = {
        k: v
        for k, v in {
            "q": q,
            "status": status_filter,
            "department": department,
            "tag": tag,
            "security": security,
            "sort": sort,
            "order": order,
        }.items()
        if v is not None and v != ""
    }

    return DocumentListResponse(
        documents=page,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
        collection=COLLECTION,
        filters_applied=filters_applied,
    )


@router.get("/{document_id}", response_model=DocumentSummary)
async def get_document(document_id: str) -> DocumentSummary:
    document_id = (document_id or "").strip()
    if not document_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid document_id")

    points = await _scroll_all_points()
    docs = _group_documents(points)
    for d in docs:
        if d.document_id == document_id or d.id == document_id:
            return d
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail=f"Document '{document_id}' not found",
    )


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document(document_id: str) -> DeleteResponse:
    """Delete all Qdrant points for this document_id (payload filter)."""
    from qdrant_client.http import models as qm

    document_id = (document_id or "").strip()
    if not document_id or len(document_id) > 80:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid document_id")

    client = await _client()
    points_deleted = 0

    try:
        # Count first for a useful response
        try:
            points_deleted = await _count_points_for_doc(document_id)
        except Exception:
            points_deleted = 0

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
            points = await _scroll_all_points()
            ids: list[Any] = []
            for p in points:
                payload = getattr(p, "payload", None) or {}
                if not isinstance(payload, dict):
                    continue
                if _payload_doc_id(payload, getattr(p, "id", "")) == document_id:
                    ids.append(getattr(p, "id"))
            if not ids:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    detail=f"Document '{document_id}' not found in vector store",
                )
            await client.delete(
                collection_name=COLLECTION,
                points_selector=qm.PointIdsList(points=ids),
            )
            points_deleted = len(ids)
        elif points_deleted == 0:
            # Filter delete ran but we couldn't count — still report success
            points_deleted = 0

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("delete document failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delete failed: {exc}",
        ) from exc

    return DeleteResponse(
        status="deleted",
        document_id=document_id,
        points_deleted=max(points_deleted, 0),
        message=f"Removed vector points for document_id={document_id}",
    )
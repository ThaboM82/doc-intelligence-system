"""
Document ingest: text extract → chunk → embed → Qdrant upsert.

Env:
  QDRANT_COLLECTION / QDRANT_COLLECTION_NAME (default document_intelligence)
  INGEST_CHUNK_SIZE (800), INGEST_CHUNK_OVERLAP (120)
  INGEST_EMBED_BATCH (16), INGEST_UPSERT_BATCH (64)
  UPLOAD_DIR, QUARANTINE_DIR
  MAX_INGEST_CHARS (optional hard cap on extracted text)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION = os.getenv("QDRANT_COLLECTION") or os.getenv(
    "QDRANT_COLLECTION_NAME", "document_intelligence"
)
CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("INGEST_CHUNK_OVERLAP", "120"))
EMBED_BATCH = int(os.getenv("INGEST_EMBED_BATCH", "16"))
UPSERT_BATCH = int(os.getenv("INGEST_UPSERT_BATCH", "64"))
MAX_INGEST_CHARS = int(os.getenv("MAX_INGEST_CHARS", "500000"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "backend/data/uploads"))
QUARANTINE_DIR = Path(os.getenv("QUARANTINE_DIR", "backend/data/quarantine"))

_POINT_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # URL namespace


@dataclass
class IngestResult:
    document_id: str
    filename: str
    status: str  # indexed | quarantined | failed
    chunks_upserted: int = 0
    security_scan_passed: bool = True
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    char_count: int = 0
    processing_time_ms: float = 0.0
    collection: str = COLLECTION


def _point_id(doc_id: str, chunk_idx: int) -> str:
    return str(uuid.uuid5(_POINT_NS, f"{doc_id}:{chunk_idx}"))


def _safe_filename(name: str) -> str:
    base = Path(name or "upload.bin").name
    base = re.sub(r"[^\w.\- ()[\]]+", "_", base)
    return base[:180] or "upload.bin"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_text_with_pages(filename: str, raw: bytes) -> tuple[str, list[tuple[int, str]]]:
    """
    Returns (full_text, [(page_number, page_text), ...]).
    page_number is 1-based when known; single (0, text) for non-paged formats.
    """
    name = (filename or "upload.bin").lower()

    if name.endswith((".txt", ".md", ".csv", ".html", ".htm", ".json", ".log")):
        text = raw.decode("utf-8", errors="replace")
        return text, [(0, text)]

    if name.endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            pages: list[tuple[int, str]] = []
            for i, page in enumerate(reader.pages, start=1):
                t = (page.extract_text() or "").strip()
                pages.append((i, t))
            full = "\n\n".join(t for _, t in pages if t).strip()
            return full, pages
        except Exception as exc:
            logger.warning("PDF extract failed: %s", exc)
            text = raw.decode("utf-8", errors="replace")
            return text, [(0, text)]

    if name.endswith(".docx"):
        try:
            import io

            from docx import Document

            doc = Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs if p.text).strip()
            return text, [(0, text)]
        except Exception as exc:
            logger.warning("DOCX extract failed: %s", exc)
            text = raw.decode("utf-8", errors="replace")
            return text, [(0, text)]

    text = raw.decode("utf-8", errors="replace")
    return text, [(0, text)]


def extract_text(filename: str, raw: bytes) -> str:
    full, _ = extract_text_with_pages(filename, raw)
    return full


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            br = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if br > size * 0.4:
                end = start + br + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_pages(
    pages: list[tuple[int, str]],
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[tuple[str, int | None]]:
    """Return list of (chunk_text, page_number|None)."""
    out: list[tuple[str, int | None]] = []
    for page_no, page_text in pages:
        if not (page_text or "").strip():
            continue
        for ch in chunk_text(page_text, size=size, overlap=overlap):
            out.append((ch, page_no if page_no > 0 else None))
    if out:
        return out
    # fallback: whole doc
    full = "\n\n".join(t for _, t in pages if t)
    return [(c, None) for c in chunk_text(full, size=size, overlap=overlap)]


# ---------------------------------------------------------------------------
# Embed + upsert
# ---------------------------------------------------------------------------


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-friendly embedding via embed_query (OpenAI path)."""
    from backend.services.embeddings import embed_query

    # Try OpenAI batch API if available for speed
    if os.getenv("OPENAI_API_KEY") and len(texts) > 1:
        try:
            return await _openai_embed_batch(texts)
        except Exception as exc:
            logger.warning("Batch embed failed, falling back per-chunk: %s", exc)

    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        vectors = await asyncio.gather(*[embed_query(t) for t in batch])
        out.extend(vectors)
    return out


async def _openai_embed_batch(texts: list[str]) -> list[list[float]]:
    import asyncio

    from openai import OpenAI

    model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    def _run(batch: list[str]) -> list[list[float]]:
        client = OpenAI()
        res = client.embeddings.create(input=batch, model=model)
        # API returns in order
        return [list(item.embedding) for item in res.data]

    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        all_vecs.extend(await asyncio.to_thread(_run, batch))
    return all_vecs


async def _upsert_chunks(
    doc_id: str,
    filename: str,
    chunk_rows: list[tuple[str, int | None]],
    vectors: list[list[float]],
    extra_payload: dict[str, Any] | None = None,
) -> int:
    from qdrant_client.http import models

    from backend.db.qdrant import get_qdrant_client

    if len(chunk_rows) != len(vectors):
        raise ValueError("chunks/vectors length mismatch")

    client = await get_qdrant_client()
    points = []
    base_payload = dict(extra_payload or {})

    for i, ((text, page), vec) in enumerate(zip(chunk_rows, vectors)):
        payload: dict[str, Any] = {
            **base_payload,
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}:{i}",
            "source_file": filename,
            "file_name": filename,
            "text": text,
            "chunk_index": i,
        }
        if page is not None:
            payload["page"] = page
        points.append(
            models.PointStruct(
                id=_point_id(doc_id, i),
                vector=vec,
                payload=payload,
            )
        )

    for i in range(0, len(points), UPSERT_BATCH):
        await client.upsert(
            collection_name=COLLECTION,
            points=points[i : i + UPSERT_BATCH],
            wait=True,
        )
    return len(points)


async def delete_document_vectors(doc_id: str) -> int:
    """Remove all points for a document (filter on payload doc_id)."""
    from qdrant_client.http import models

    from backend.db.qdrant import get_qdrant_client

    client = await get_qdrant_client()
    await client.delete(
        collection_name=COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
    return 0  # Qdrant delete does not always return count


def _save_bytes(directory: Path, doc_id: str, filename: str, raw: bytes) -> Path | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{doc_id}_{filename}"
        path.write_bytes(raw)
        return path
    except Exception as exc:
        logger.warning("Failed to write %s: %s", directory, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def ingest_bytes(
    filename: str,
    raw: bytes,
    *,
    skip_security: bool = False,
    metadata: dict[str, Any] | None = None,
    document_id: str | None = None,
) -> IngestResult:
    t0 = time.perf_counter()
    doc_id = document_id or str(uuid.uuid4())
    warnings: list[str] = []
    safe_name = _safe_filename(filename)

    # --- Security scan ---
    security_ok = True
    if not skip_security:
        try:
            from backend.security.validators import PromptInjectionDetector

            sample = raw[:80_000].decode("utf-8", errors="replace")
            report = PromptInjectionDetector.scan_text(sample)
            if getattr(report, "is_flagged", False):
                security_ok = False
                _save_bytes(QUARANTINE_DIR, doc_id, safe_name, raw)
                patterns = list(getattr(report, "matched_patterns", None) or [])
                ms = round((time.perf_counter() - t0) * 1000, 2)
                return IngestResult(
                    document_id=doc_id,
                    filename=safe_name,
                    status="quarantined",
                    security_scan_passed=False,
                    message="Document flagged by security scan; not indexed.",
                    warnings=patterns,
                    processing_time_ms=ms,
                )
        except Exception as exc:
            warnings.append(f"Security scan skipped: {exc}")

    # --- Extract ---
    full_text, pages = extract_text_with_pages(safe_name, raw)
    if len(full_text) > MAX_INGEST_CHARS:
        full_text = full_text[:MAX_INGEST_CHARS]
        pages = [(0, full_text)]
        warnings.append(f"Text truncated to {MAX_INGEST_CHARS} characters.")

    if not full_text.strip():
        ms = round((time.perf_counter() - t0) * 1000, 2)
        return IngestResult(
            document_id=doc_id,
            filename=safe_name,
            status="failed",
            security_scan_passed=security_ok,
            message="No extractable text in file.",
            warnings=warnings,
            processing_time_ms=ms,
        )

    chunk_rows = chunk_pages(pages)
    if not chunk_rows:
        ms = round((time.perf_counter() - t0) * 1000, 2)
        return IngestResult(
            document_id=doc_id,
            filename=safe_name,
            status="failed",
            security_scan_passed=security_ok,
            message="Chunking produced no segments.",
            warnings=warnings,
            char_count=len(full_text),
            processing_time_ms=ms,
        )

    _save_bytes(UPLOAD_DIR, doc_id, safe_name, raw)

    extra = dict(metadata or {})
    extra.setdefault("ingested_at", time.time())

    try:
        texts = [c[0] for c in chunk_rows]
        vectors = await _embed_texts(texts)
        n = await _upsert_chunks(
            doc_id, safe_name, chunk_rows, vectors, extra_payload=extra
        )
    except Exception as exc:
        logger.exception("Ingest upsert failed")
        ms = round((time.perf_counter() - t0) * 1000, 2)
        return IngestResult(
            document_id=doc_id,
            filename=safe_name,
            status="failed",
            security_scan_passed=security_ok,
            message=f"Indexing failed: {exc}",
            warnings=warnings,
            char_count=len(full_text),
            processing_time_ms=ms,
        )

    ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Ingested doc_id=%s file=%s chunks=%s chars=%s ms=%.1f collection=%s",
        doc_id,
        safe_name,
        n,
        len(full_text),
        ms,
        COLLECTION,
    )
    return IngestResult(
        document_id=doc_id,
        filename=safe_name,
        status="indexed",
        chunks_upserted=n,
        security_scan_passed=security_ok,
        message=f"Indexed {n} chunk(s) into '{COLLECTION}'.",
        warnings=warnings,
        char_count=len(full_text),
        processing_time_ms=ms,
    )
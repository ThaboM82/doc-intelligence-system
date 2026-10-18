"""
Enterprise Document Pipeline Dispatcher & Advanced Chunk Analysis Engine.
Handles sliding-window chunking, asynchronous processing, zero-width character detection,
advanced threat & prompt-injection risk aggregation, batch processing, telemetry hooks,
and vector indexing resilience.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ChunkAnalysisResult(BaseModel):
    chunk_index: int
    char_offset: int
    content: str
    risk_score: float = 0.0
    flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineProcessingOutput(BaseModel):
    document_id: str
    status: str = "processed"  # "processed", "quarantined", "flagged_for_review"
    overall_risk_score: float = 0.0
    security_flagged: bool = False
    flagged_chunks_count: int = 0
    total_chunks: int = 0
    chunk_results: list[ChunkAnalysisResult] = Field(default_factory=list)
    extracted_metadata: dict[str, Any] = Field(default_factory=dict)
    header_validation: Any | None = None
    threat_breakdown: dict[str, float] = Field(default_factory=dict)
    processing_duration_ms: float = 0.0


class DocumentPipelineDispatcher:
    def __init__(
        self,
        vector_store: Any = None,
        chunk_size: int = 100,
        chunk_overlap: int = 20,
        embedding_dim: int = 384,
        quarantine_threshold: float = 0.50,
        review_threshold: float = 0.35,
        metrics_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.vector_store = vector_store
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_dim = embedding_dim
        self.quarantine_threshold = quarantine_threshold
        self.review_threshold = review_threshold
        self.metrics_callback = metrics_callback

        # Compiled threat patterns for high-performance scanning
        self._injection_patterns = [
            re.compile(r"ignore all previous instructions", re.IGNORECASE),
            re.compile(r"system override", re.IGNORECASE),
            re.compile(r"developer mode", re.IGNORECASE),
            re.compile(r"dump system prompt", re.IGNORECASE),
            re.compile(r"show api keys", re.IGNORECASE),
            re.compile(r"display system secrets", re.IGNORECASE),
        ]
        self._zero_width_pattern = re.compile(r"[\u200B\u200C\u200D\uFEFF]")
        self._credential_pattern = re.compile(
            r"(api[_-]?key|secret[_-]?key|password|bearer\s+[a-zA-Z0-9_\-\.]+)",
            re.IGNORECASE,
        )

    def chunk_text(self, text: str | None) -> list[dict[str, Any]]:
        """Splits text into overlapping sliding-window chunks with exact character offsets."""
        if text is None:
            return []
        if not isinstance(text, str):
            text = str(text)

        cleaned = text.strip()
        if not cleaned:
            return []

        chunks: list[dict[str, Any]] = []
        stride = max(1, self.chunk_size - self.chunk_overlap)
        length = len(text)
        char_offset = 0
        index = 0

        while char_offset < length:
            end_offset = min(char_offset + self.chunk_size, length)
            chunk_content = text[char_offset:end_offset]

            chunks.append(
                {
                    "chunk_index": index,
                    "char_offset": char_offset,
                    "content": chunk_content,
                }
            )

            if end_offset == length:
                break

            char_offset += stride
            index += 1

        return chunks

    async def achunk_text(self, text: str | None) -> list[dict[str, Any]]:
        """Asynchronous wrapper for text chunking."""
        return await asyncio.to_thread(self.chunk_text, text)

    def analyze_chunk(self, chunk_index: int, char_offset: int, content: str) -> ChunkAnalysisResult:
        """Performs deep security and structural analysis on a single text chunk."""
        risk = 0.0
        flags: list[str] = []
        chunk_meta: dict[str, Any] = {
            "length": len(content),
            "word_count": len(content.split()),
        }
        category_risks = {"obfuscation": 0.0, "injection": 0.0, "credentials": 0.0}

        # 1. Zero-width Unicode Obfuscation check
        if self._zero_width_pattern.search(content):
            obfs_risk = 0.40
            category_risks["obfuscation"] = obfs_risk
            risk = max(risk, obfs_risk)
            flag = "Zero-width unicode obfuscation detected"
            flags.append(flag)
            chunk_meta["zero_width_obfuscation"] = True

        # 2. Prompt Injection signature detection
        for pattern in self._injection_patterns:
            if pattern.search(content):
                inj_risk = 0.55
                category_risks["injection"] = max(category_risks["injection"], inj_risk)
                risk = max(risk, inj_risk)
                flag = f"Prompt injection pattern detected: {pattern.pattern}"
                if flag not in flags:
                    flags.append(flag)
                chunk_meta["prompt_injection"] = True

        # 3. Credential / Secret leakage pattern check
        if self._credential_pattern.search(content):
            cred_risk = 0.45
            category_risks["credentials"] = cred_risk
            risk = max(risk, cred_risk)
            flag = "Potential API key or credential exposure detected"
            if flag not in flags:
                flags.append(flag)
            chunk_meta["credential_exposure"] = True

        chunk_meta["category_risks"] = category_risks

        return ChunkAnalysisResult(
            chunk_index=chunk_index,
            char_offset=char_offset,
            content=content,
            risk_score=risk,
            flags=flags,
            metadata=chunk_meta,
        )

    def process_document(
        self,
        document_id: str,
        raw_text: str | None,
        headers: dict[str, str] | None = None,
        auto_index_vectors: bool = True,
    ) -> PipelineProcessingOutput:
        """Processes document chunks, executes security threat analysis, aggregates risk, and coordinates vector indexing."""
        start_time = time.perf_counter()
        raw_text = raw_text or ""
        chunks_data = self.chunk_text(raw_text)
        total_chunks = len(chunks_data)

        chunk_results: list[ChunkAnalysisResult] = []
        max_risk = 0.0
        flagged_count = 0
        quarantine_reasons: list[str] = []
        threat_scores = {"obfuscation": 0.0, "injection": 0.0, "credentials": 0.0, "headers": 0.0}

        for c in chunks_data:
            analysis = self.analyze_chunk(
                chunk_index=c["chunk_index"],
                char_offset=c["char_offset"],
                content=c["content"],
            )
            chunk_results.append(analysis)

            if analysis.risk_score >= self.review_threshold:
                flagged_count += 1

            max_risk = max(max_risk, analysis.risk_score)
            cat_risks = analysis.metadata.get("category_risks", {})
            for k, v in cat_risks.items():
                threat_scores[k] = max(threat_scores[k], v)

            for flag in analysis.flags:
                if "quarantine" in flag.lower() or analysis.risk_score >= self.quarantine_threshold:
                    if flag not in quarantine_reasons:
                        quarantine_reasons.append(flag)

        # Header Validation integration if email headers are present
        header_validation_result = None
        if headers:
            try:
                from backend.security.validators import HeaderValidator

                header_validation_result = HeaderValidator.verify_spf_dkim_dmarc(headers)
                if header_validation_result:
                    header_risk = getattr(header_validation_result, "risk_score", 0.0)
                    threat_scores["headers"] = header_risk
                    max_risk = max(max_risk, header_risk)
                    if getattr(header_validation_result, "is_suspicious", False):
                        reason = "Email header security validation failed (SPF/DKIM/DMARC)"
                        if reason not in quarantine_reasons:
                            quarantine_reasons.append(reason)
            except Exception as exc:
                logger.debug("Header validation skipped or failed: %s", exc)

        # Determine final pipeline status
        security_flagged = max_risk >= self.review_threshold or bool(quarantine_reasons)
        status_val = "processed"

        if max_risk >= self.quarantine_threshold or quarantine_reasons:
            status_val = "quarantined"
        elif self.review_threshold <= max_risk < self.quarantine_threshold:
            status_val = "flagged_for_review"

        # Vector indexing with graceful exception resilience
        if auto_index_vectors and status_val != "quarantined" and self.vector_store:
            try:
                self.vector_store.upsert_chunks(document_id=document_id, chunks=chunks_data)
            except Exception as exc:
                logger.warning("Vector store upsert failed gracefully for %s: %s", document_id, exc)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        if self.metrics_callback:
            try:
                self.metrics_callback(
                    document_id,
                    {"status": status_val, "risk_score": max_risk, "duration_ms": duration_ms},
                )
            except Exception as cb_exc:
                logger.debug("Metrics callback failed: %s", cb_exc)

        words = raw_text.split()
        extracted_metadata = {
            "char_count": len(raw_text),
            "word_count": len(words),
            "chunk_count": total_chunks,
            "language": "en",
        }
        if quarantine_reasons:
            extracted_metadata["quarantine_reasons"] = quarantine_reasons

        return PipelineProcessingOutput(
            document_id=document_id,
            status=status_val,
            overall_risk_score=max_risk,
            security_flagged=security_flagged,
            flagged_chunks_count=flagged_count,
            total_chunks=total_chunks,
            chunk_results=chunk_results,
            extracted_metadata=extracted_metadata,
            header_validation=header_validation_result,
            threat_breakdown=threat_scores,
            processing_duration_ms=round(duration_ms, 2),
        )

    async def aprocess_document(
        self,
        document_id: str,
        raw_text: str | None,
        headers: dict[str, str] | None = None,
        auto_index_vectors: bool = True,
    ) -> PipelineProcessingOutput:
        """Asynchronous document processing pipeline wrapper."""
        return await asyncio.to_thread(
            self.process_document,
            document_id=document_id,
            raw_text=raw_text,
            headers=headers,
            auto_index_vectors=auto_index_vectors,
        )

    async def process_batch_documents(
        self, documents: list[dict[str, Any]], auto_index_vectors: bool = True
    ) -> list[PipelineProcessingOutput]:
        """Processes a batch of documents concurrently using asyncio.gather."""
        tasks = [
            self.aprocess_document(
                document_id=doc.get("document_id", f"doc_{i}"),
                raw_text=doc.get("raw_text", ""),
                headers=doc.get("headers"),
                auto_index_vectors=auto_index_vectors,
            )
            for i, doc in enumerate(documents)
        ]
        return await asyncio.gather(*tasks)
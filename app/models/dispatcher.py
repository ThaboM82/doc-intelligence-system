"""
app/models/dispatcher.py

Central Dispatcher for Document Intelligence.
Coordinates document chunking, security scanning, vector store indexing,
downstream entity extraction, and batch document workflows.
"""

import logging
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from app.database.vector_store import DocumentChunk, VectorStoreManager
from app.security.validators import (
    HeaderValidationResult,
    HeaderValidator,
    PromptInjectionDetector,
    PromptInjectionResult,
)

logger = logging.getLogger("document_intelligence_api.models.dispatcher")


# ==============================================================================
# Pipeline Models & Data Transfer Objects
# ==============================================================================

class ChunkAnalysisResult(BaseModel):
    chunk_index: int
    char_offset: int
    text_snippet: str
    scan_result: PromptInjectionResult


class ExtractedEntities(BaseModel):
    emails: list[str] = Field(default_factory=list)
    ipv4_addresses: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    monetary_values: list[str] = Field(default_factory=list)
    potential_api_keys: list[str] = Field(default_factory=list)


class PipelineProcessingOutput(BaseModel):
    document_id: str
    status: str  # "processed", "quarantined", "flagged_for_review"
    overall_risk_score: float
    security_flagged: bool
    total_chunks: int
    flagged_chunks_count: int
    processing_time_ms: float = 0.0
    header_validation: HeaderValidationResult | None = None
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    extracted_metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_findings: list[ChunkAnalysisResult] = Field(default_factory=list)


class BatchPipelineOutput(BaseModel):
    total_documents: int
    processed_count: int
    quarantined_count: int
    flagged_count: int
    total_batch_time_ms: float
    results: list[PipelineProcessingOutput] = Field(default_factory=list)


# ==============================================================================
# Dispatcher Engine
# ==============================================================================

class DocumentPipelineDispatcher:
    """
    Dispatches documents through text chunking, safeguard validation,
    vector store indexing, entity extraction, and structured batch workflows.
    """

    def __init__(
        self,
        vector_store: VectorStoreManager | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        embedding_dim: int = 384
    ):
        self.vector_store = vector_store or VectorStoreManager()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_dim = embedding_dim

    def chunk_text(self, text: str) -> list[dict[str, Any]]:
        """
        Splits raw document text into overlapping sliding-window chunks.
        """
        if not text:
            return []

        chunks = []
        start = 0
        text_length = len(text)
        chunk_idx = 0
        stride = max(1, self.chunk_size - self.chunk_overlap)

        while start < text_length:
            end = min(start + self.chunk_size, text_length)
            chunk_content = text[start:end]

            chunks.append({
                "chunk_index": chunk_idx,
                "char_offset": start,
                "content": chunk_content
            })

            chunk_idx += 1
            start += stride

        return chunks

    def extract_entities(self, text: str) -> ExtractedEntities:
        """
        Extracts key security indicators and structural entities from document content.
        """
        if not text:
            return ExtractedEntities()

        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
        currency_pattern = r'\$(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?|\b\d+\s?(?:USD|EUR|GBP|ZAR)\b'
        api_key_pattern = r'\b(?:sk_live|sk_test|key|token|api_key)_[a-zA-Z0-9]{16,64}\b'

        return ExtractedEntities(
            emails=list(set(re.findall(email_pattern, text))),
            ipv4_addresses=list(set(re.findall(ip_pattern, text))),
            urls=list(set(re.findall(url_pattern, text))),
            monetary_values=list(set(re.findall(currency_pattern, text, re.IGNORECASE))),
            potential_api_keys=list(set(re.findall(api_key_pattern, text, re.IGNORECASE)))
        )

    def process_document(
        self,
        document_id: str,
        raw_text: str,
        headers: dict[str, str] | None = None,
        auto_index_vectors: bool = True
    ) -> PipelineProcessingOutput:
        """
        Executes the end-to-end document intelligence pipeline:
        1. Validate email/transport headers (if present).
        2. Chunk text and scan each chunk for prompt injections/anomalies.
        3. Extract threat intelligence entities and structural metadata.
        4. Evaluate aggregated document risk score.
        5. Quarantine or index vector embeddings in Qdrant.
        6. Return pipeline processing results and extracted metadata.
        """
        start_time = time.time()
        logger.info(f"Processing document ID '{document_id}' through intelligence pipeline.")

        # Step 1: Validate Headers
        header_result = None
        header_risk = 0.0
        if headers:
            header_result = HeaderValidator.verify_spf_dkim_dmarc(headers)
            header_risk = header_result.risk_score

        # Step 2: Chunk Document Text
        raw_chunks = self.chunk_text(raw_text)
        chunk_findings: list[ChunkAnalysisResult] = []
        vector_chunks_to_index: list[DocumentChunk] = []

        max_prompt_risk = 0.0
        flagged_chunks_count = 0

        # Step 3: Scan Each Chunk
        for chunk in raw_chunks:
            idx = chunk["chunk_index"]
            content = chunk["content"]
            scan = PromptInjectionDetector.scan_text(content)

            chunk_findings.append(
                ChunkAnalysisResult(
                    chunk_index=idx,
                    char_offset=chunk["char_offset"],
                    text_snippet=content[:80] + "..." if len(content) > 80 else content,
                    scan_result=scan
                )
            )

            if scan.is_flagged:
                flagged_chunks_count += 1
                if scan.risk_score > max_prompt_risk:
                    max_prompt_risk = scan.risk_score

            # Prepare vector chunk (dummy/mock embedding vector used if embedding model is offloaded)
            mock_embedding = [0.01 * (idx + 1)] * self.embedding_dim
            vector_chunks_to_index.append(
                DocumentChunk(
                    chunk_id=f"{document_id}_{idx}",
                    document_id=document_id,
                    content=content,
                    embedding=mock_embedding,
                    security_flagged=scan.is_flagged,
                    risk_score=scan.risk_score,
                    metadata={"chunk_index": idx, "char_offset": chunk["char_offset"]}
                )
            )

        # Step 4: Extract Key Entities
        extracted_entities = self.extract_entities(raw_text)

        # Step 5: Overall Risk Assessment
        overall_risk = round(max(max_prompt_risk, header_risk), 2)
        
        is_suspicious_header = bool(header_result.is_suspicious) if header_result is not None else False
        security_flagged = bool(flagged_chunks_count > 0 or is_suspicious_header)

        # Determine Processing Status
        if overall_risk >= 0.70 or flagged_chunks_count > 0:
            status = "quarantined"
        elif overall_risk >= 0.35:
            status = "flagged_for_review"
        else:
            status = "processed"

        # Step 6: Index Vectors in Qdrant (Only for safe or review-flagged documents)
        if auto_index_vectors and status != "quarantined" and self.vector_store:
            try:
                self.vector_store.upsert_chunks(vector_chunks_to_index)
            except Exception as e:
                logger.error(f"Failed to automatically index vector chunks for '{document_id}': {e}")

        # Step 7: Construct Extracted Metadata & Latency
        duration_ms = round((time.time() - start_time) * 1000, 2)
        extracted_metadata = {
            "char_count": len(raw_text) if raw_text else 0,
            "word_count": len(raw_text.split()) if raw_text else 0,
            "chunk_count": len(raw_chunks),
            "language": "en",
            "quarantine_reasons": [
                anomaly
                for chunk_finding in chunk_findings
                for anomaly in chunk_finding.scan_result.detected_anomalies
            ]
        }

        return PipelineProcessingOutput(
            document_id=document_id,
            status=status,
            overall_risk_score=overall_risk,
            security_flagged=security_flagged,
            total_chunks=len(raw_chunks),
            flagged_chunks_count=flagged_chunks_count,
            processing_time_ms=duration_ms,
            header_validation=header_result,
            extracted_entities=extracted_entities,
            extracted_metadata=extracted_metadata,
            chunk_findings=chunk_findings,
        )

    def process_batch(
        self,
        documents: list[dict[str, Any]],
        auto_index_vectors: bool = True
    ) -> BatchPipelineOutput:
        """
        Processes a collection of documents sequentially, returning consolidated stats.
        """
        start_time = time.time()
        results: list[PipelineProcessingOutput] = []

        processed = 0
        quarantined = 0
        flagged = 0

        for doc in documents:
            doc_id = doc.get("document_id", "doc_unknown")
            text = doc.get("raw_text", "")
            hdrs = doc.get("headers")

            out = self.process_document(
                document_id=doc_id,
                raw_text=text,
                headers=hdrs,
                auto_index_vectors=auto_index_vectors
            )

            if out.status == "quarantined":
                quarantined += 1
            elif out.status == "flagged_for_review":
                flagged += 1
            else:
                processed += 1

            results.append(out)

        total_time = round((time.time() - start_time) * 1000, 2)

        return BatchPipelineOutput(
            total_documents=len(documents),
            processed_count=processed,
            quarantined_count=quarantined,
            flagged_count=flagged,
            total_batch_time_ms=total_time,
            results=results
        )

    def force_quarantine(
        self,
        pipeline_output: PipelineProcessingOutput,
        reason: str
    ) -> PipelineProcessingOutput:
        """
        Manually escalates a document's status to quarantined.
        """
        pipeline_output.status = "quarantined"
        pipeline_output.security_flagged = True
        pipeline_output.overall_risk_score = max(pipeline_output.overall_risk_score, 0.95)
        
        reasons = pipeline_output.extracted_metadata.get("quarantine_reasons", [])
        reasons.append(f"Manual Override: {reason}")
        pipeline_output.extracted_metadata["quarantine_reasons"] = reasons

        logger.warning(f"Document '{pipeline_output.document_id}' manually escalated to quarantined: {reason}")
        return pipeline_output
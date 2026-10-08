import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.vectorstore.qdrant_store import QdrantStoreConfig, QdrantVectorStore
from pydantic import BaseModel, Field

from backend.embeddings.manager import EmbeddingManager
from backend.ingestion.chunker import DocumentChunk, DocumentChunker

logger = logging.getLogger(__name__)


class PipelineStage(BaseModel):
    stage_name: str
    status: str = "pending"  # pending, in_progress, completed, failed
    progress_percentage: float = 0.0
    details: str | None = None


class IngestionTaskStatus(BaseModel):
    task_id: str
    document_id: str
    file_name: str
    status: str = "QUEUED"  # QUEUED, PARSING, EMBEDDING, INDEXING, COMPLETED, FAILED
    stages: list[PipelineStage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    chunks_indexed: int = 0
    error_message: str | None = None


class IngestionPipeline:
    def __init__(
        self,
        vector_store: QdrantVectorStore | None = None,
        chunker: DocumentChunker | None = None,
        embedding_manager: EmbeddingManager | None = None,
    ):
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.vector_store = vector_store or QdrantVectorStore(
            config=QdrantStoreConfig(),
            embedding_manager=self.embedding_manager,
        )
        self.chunker = chunker or DocumentChunker()
        self.tasks_db: dict[str, IngestionTaskStatus] = {}

    async def setup(self, force_recreate: bool = False) -> None:
        """Ensure Qdrant collection and payload indexes exist."""
        await self.vector_store.initialize_collection(
            hybrid=True, force_recreate=force_recreate
        )

    def create_task(self, file_name: str, document_id: str | None = None) -> IngestionTaskStatus:
        """Create and track an ingestion task state."""
        task_id = str(uuid.uuid4())
        doc_id = document_id or str(uuid.uuid4())
        
        stages = [
            PipelineStage(stage_name="Parsing & Chunking"),
            PipelineStage(stage_name="Embedding Generation & Vector Upsert"),
        ]
        task = IngestionTaskStatus(
            task_id=task_id,
            document_id=doc_id,
            file_name=file_name,
            stages=stages,
        )
        self.tasks_db[task_id] = task
        return task

    def get_task_status(self, task_id: str) -> IngestionTaskStatus | None:
        """Retrieve task tracking metadata by task ID."""
        return self.tasks_db.get(task_id)

    async def process_and_index_document(
        self,
        file_path: str | Path,
        file_name: str,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Ingest a single document: chunk content, generate dual embeddings, and store in Qdrant."""
        doc_id = document_id or str(uuid.uuid4())
        path = Path(file_path)

        if not path.exists():
            if task_id:
                self._fail_task(task_id, f"File not found: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Ingesting document '{file_name}' (ID: {doc_id})")

        if task_id:
            self._update_stage(task_id, "Parsing & Chunking", "in_progress", 10.0)

        # 1. Parse and chunk document content (offloaded to thread for async non-blocking execution)
        chunks: list[DocumentChunk] = await asyncio.to_thread(
            self.chunker.chunk_file,
            file_path=str(path),
            file_name=file_name,
            document_id=doc_id,
            extra_metadata=metadata or {},
        )

        if not chunks:
            logger.warning(f"No text chunks generated for file '{file_name}'")
            if task_id:
                self._update_stage(task_id, "Parsing & Chunking", "completed", 100.0)
                self._complete_task(task_id, chunks_indexed=0, status="SKIPPED")
            return {
                "status": "skipped",
                "document_id": doc_id,
                "file_name": file_name,
                "chunks_indexed": 0,
            }

        if task_id:
            self._update_stage(task_id, "Parsing & Chunking", "completed", 100.0)
            self._update_stage(task_id, "Embedding Generation & Vector Upsert", "in_progress", 30.0)

        # 2. Dual-Embed (Dense + BM25 Sparse) & Upsert into Qdrant
        success = await self.vector_store.upsert_chunks(chunks=chunks, hybrid=True)

        if not success:
            err_msg = f"Failed to upsert chunks for document '{file_name}' to Qdrant"
            if task_id:
                self._fail_task(task_id, err_msg)
            raise RuntimeError(err_msg)

        logger.info(f"Successfully indexed {len(chunks)} chunks for '{file_name}'")

        if task_id:
            self._update_stage(task_id, "Embedding Generation & Vector Upsert", "completed", 100.0)
            self._complete_task(task_id, chunks_indexed=len(chunks))

        return {
            "status": "success",
            "document_id": doc_id,
            "file_name": file_name,
            "chunks_indexed": len(chunks),
        }

    async def process_and_index_text(
        self,
        text: str,
        file_name: str,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ingest raw text directly into Qdrant without saving to disk first."""
        doc_id = document_id or str(uuid.uuid4())
        logger.info(f"Ingesting raw text payload as '{file_name}' (ID: {doc_id})")

        chunks: list[DocumentChunk] = await asyncio.to_thread(
            self.chunker.chunk_text,
            text=text,
            file_name=file_name,
            document_id=doc_id,
            extra_metadata=metadata or {},
        )

        if not chunks:
            return {
                "status": "skipped",
                "document_id": doc_id,
                "file_name": file_name,
                "chunks_indexed": 0,
            }

        success = await self.vector_store.upsert_chunks(chunks=chunks, hybrid=True)
        if not success:
            raise RuntimeError(f"Failed to upsert raw text chunks for '{file_name}' to Qdrant")

        return {
            "status": "success",
            "document_id": doc_id,
            "file_name": file_name,
            "chunks_indexed": len(chunks),
        }

    async def process_batch(
        self,
        files: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Process multiple documents in parallel batch mode.
        `files` list format: [{"file_path": "...", "file_name": "...", "metadata": {...}}, ...]
        """
        tasks = [
            self.process_and_index_document(
                file_path=item["file_path"],
                file_name=item["file_name"],
                document_id=item.get("document_id"),
                metadata=item.get("metadata"),
            )
            for item in files
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def remove_document(self, document_id: str) -> bool:
        """Remove a document and its associated vectors from Qdrant."""
        return await self.vector_store.delete_document_chunks(document_id=document_id)

    # Private internal status tracking helpers
    def _update_stage(self, task_id: str, stage_name: str, status: str, progress: float):
        if task := self.tasks_db.get(task_id):
            task.status = stage_name.upper().replace(" ", "_")
            for stage in task.stages:
                if stage.stage_name == stage_name:
                    stage.status = status
                    stage.progress_percentage = round(progress, 2)
                    break

    def _complete_task(self, task_id: str, chunks_indexed: int, status: str = "COMPLETED"):
        if task := self.tasks_db.get(task_id):
            task.status = status
            task.chunks_indexed = chunks_indexed

    def _fail_task(self, task_id: str, error_msg: str):
        if task := self.tasks_db.get(task_id):
            task.status = "FAILED"
            task.error_message = error_msg
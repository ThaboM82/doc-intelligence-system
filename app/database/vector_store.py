"""
app/database/vector_store.py

Qdrant Vector Store Manager for Document Intelligence.
Handles collection creation, payload indexing, batch chunk ingestion,
filtered semantic search, and document vector lifecycle management.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qdrant_models
except ImportError:
    QdrantClient = None
    qdrant_models = None

logger = logging.getLogger("document_intelligence_api.database.vector_store")


class DocumentChunk(BaseModel):
    chunk_id: str | int
    document_id: str
    content: str
    embedding: list[float] | None = None
    security_flagged: bool = False
    risk_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    score: float
    security_flagged: bool
    risk_score: float
    metadata: dict[str, Any]


class VectorStoreManager:
    """
    Manages vector storage, payload indexing, and semantic search using Qdrant.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        vector_size: int = 384,
        collection_name: str = "document_chunks"
    ):
        self.vector_size = vector_size
        self.collection_name = collection_name

        if QdrantClient is not None:
            try:
                self.client = QdrantClient(host=host, port=port, timeout=10.0)
            except Exception as e:
                logger.error(f"Failed to initialize QdrantClient connection: {e}")
                self.client = None
        else:
            self.client = None
            logger.warning("qdrant-client package is not installed. Running in memory fallback mode.")

    def is_healthy(self) -> bool:
        """Checks if the Qdrant service is reachable."""
        if not self.client:
            return False
        try:
            self.client.get_collections()
            return True
        except Exception as e:
            logger.error(f"Qdrant health check failed: {e}")
            return False

    def init_collection(self, force_recreate: bool = False) -> bool:
        """
        Ensures the document chunk collection exists with cosine distance metric
        and builds field indexes for key metadata.
        """
        if not self.client:
            return False

        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)

            if exists and force_recreate:
                self.client.delete_collection(self.collection_name)
                exists = False
                logger.info(f"Deleted existing collection '{self.collection_name}' due to force_recreate=True.")

            if not exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qdrant_models.VectorParams(
                        size=self.vector_size,
                        distance=qdrant_models.Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection '{self.collection_name}'.")

                # Create payload indexes for fast filtered searches
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="document_id",
                    field_schema=qdrant_models.PayloadSchemaType.KEYWORD
                )
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="security_flagged",
                    field_schema=qdrant_models.PayloadSchemaType.KEYWORD
                )

            return True
        except Exception as e:
            logger.error(f"Failed to initialize collection '{self.collection_name}': {e}")
            return False

    def upsert_chunks(self, chunks: list[DocumentChunk], batch_size: int = 100) -> bool:
        """Indexes or updates document chunks in Qdrant in batches."""
        if not self.client:
            return False

        valid_chunks = [c for c in chunks if c.embedding is not None and len(c.embedding) == self.vector_size]
        if not valid_chunks:
            logger.warning("No valid chunks with embeddings provided for upsert.")
            return False

        try:
            for i in range(0, len(valid_chunks), batch_size):
                batch = valid_chunks[i : i + batch_size]
                points = [
                    qdrant_models.PointStruct(
                        id=chunk.chunk_id,
                        vector=chunk.embedding,
                        payload={
                            "document_id": chunk.document_id,
                            "content": chunk.content,
                            "security_flagged": chunk.security_flagged,
                            "risk_score": chunk.risk_score,
                            **chunk.metadata
                        }
                    )
                    for chunk in batch
                ]

                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points
                )
            logger.info(f"Successfully upserted {len(valid_chunks)} document chunks.")
            return True
        except Exception as e:
            logger.error(f"Error during chunk batch upsert: {e}")
            return False

    def search_similar(
        self,
        query_vector: list[float],
        top_k: int = 5,
        document_id: str | None = None,
        exclude_security_flagged: bool = False
    ) -> list[SearchResult]:
        """
        Performs semantic search across document chunks with optional document ID filtering
        and security flag exclusions.
        """
        if not self.client:
            return []

        if len(query_vector) != self.vector_size:
            logger.error(f"Query vector dimension mismatch. Expected {self.vector_size}, got {len(query_vector)}.")
            return []

        try:
            filter_conditions = []

            if document_id:
                filter_conditions.append(
                    qdrant_models.FieldCondition(
                        key="document_id",
                        match=qdrant_models.MatchValue(value=document_id)
                    )
                )

            if exclude_security_flagged:
                filter_conditions.append(
                    qdrant_models.FieldCondition(
                        key="security_flagged",
                        match=qdrant_models.MatchValue(value=False)
                    )
                )

            query_filter = None
            if filter_conditions:
                query_filter = qdrant_models.Filter(must=filter_conditions)

            search_hits = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k
            )

            results = []
            for hit in search_hits:
                payload = hit.payload or {}
                results.append(
                    SearchResult(
                        chunk_id=str(hit.id),
                        document_id=payload.get("document_id", ""),
                        content=payload.get("content", ""),
                        score=hit.score,
                        security_flagged=payload.get("security_flagged", False),
                        risk_score=payload.get("risk_score", 0.0),
                        metadata={
                            k: v for k, v in payload.items()
                            if k not in ("document_id", "content", "security_flagged", "risk_score")
                        }
                    )
                )
            return results
        except Exception as e:
            logger.error(f"Error performing vector similarity search: {e}")
            return []

    def delete_document_vectors(self, document_id: str) -> bool:
        """Deletes all vector chunks associated with a specific document ID."""
        if not self.client:
            return False

        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qdrant_models.FilterSelector(
                    filter=qdrant_models.Filter(
                        must=[
                            qdrant_models.FieldCondition(
                                key="document_id",
                                match=qdrant_models.MatchValue(value=document_id)
                            )
                        ]
                    )
                )
            )
            logger.info(f"Deleted vector chunks for document_id '{document_id}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete vector chunks for document_id '{document_id}': {e}")
            return False

    def get_collection_stats(self) -> dict[str, Any]:
        """Returns statistics on vector count and collection status."""
        if not self.client:
            return {"status": "offline", "vector_count": 0}

        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "status": "online",
                "collection_name": self.collection_name,
                "vector_size": self.vector_size,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
            }
        except Exception as e:
            logger.error(f"Failed to fetch collection stats: {e}")
            return {"status": "error", "message": str(e)}
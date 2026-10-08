import logging
from typing import Any

from pydantic import BaseModel, Field

try:
    from fastembed import SparseTextEmbedding
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models as qmodels
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

from backend.embeddings.manager import EmbeddingManager
from backend.ingestion.chunker import DocumentChunk

logger = logging.getLogger(__name__)


class QdrantStoreConfig(BaseModel):
    url: str = Field(default="http://localhost:6333", description="Qdrant endpoint")
    api_key: str | None = Field(default=None, description="API Key")
    collection_name: str = Field(default="phishing_docs", description="Collection name")
    vector_size: int = Field(default=384, description="Dense vector dimension")
    distance: str = Field(default="Cosine", description="Distance metric: Cosine, Euclidean, Dot")
    batch_size: int = Field(default=100, description="Max batch size for vector upserts")
    timeout: float = Field(default=30.0, description="Client request timeout in seconds")
    sparse_model_name: str = Field(
        default="Qdrant/bm25",
        description="FastEmbed model for sparse lexical embeddings (BM25 or SPLADE)",
    )


class QdrantVectorStore:
    def __init__(
        self,
        config: QdrantStoreConfig | None = None,
        embedding_manager: EmbeddingManager | None = None,
    ):
        if not QDRANT_AVAILABLE:
            raise ImportError(
                "qdrant-client and fastembed are required. Install via `pip install qdrant-client fastembed`."
            )

        self.config = config or QdrantStoreConfig()
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.config.vector_size = self.embedding_manager.config.dimension

        # Sparse Encoder for BM25/Lexical representation
        self.sparse_encoder = SparseTextEmbedding(model_name=self.config.sparse_model_name)

        self.client = AsyncQdrantClient(
            url=self.config.url,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

    async def collection_exists(self) -> bool:
        """Check if the target collection exists."""
        try:
            return await self.client.collection_exists(self.config.collection_name)
        except Exception as e:
            logger.error(f"Error checking collection existence: {e}")
            return False

    async def initialize_collection(
        self, hybrid: bool = True, force_recreate: bool = False
    ) -> None:
        """Initialize collection with payload indexes and optional sparse vector support."""
        exists = await self.collection_exists()

        if exists and force_recreate:
            logger.warning(f"Recreating existing collection '{self.config.collection_name}'")
            await self.client.delete_collection(self.config.collection_name)
            exists = False

        if not exists:
            distance_map = {
                "Cosine": qmodels.Distance.COSINE,
                "Euclidean": qmodels.Distance.EUCLID,
                "Dot": qmodels.Distance.DOT,
            }
            qdistance = distance_map.get(self.config.distance, qmodels.Distance.COSINE)

            if hybrid:
                logger.info(
                    f"Creating Hybrid Qdrant collection '{self.config.collection_name}' "
                    f"({self.config.vector_size}d dense + sparse BM25)"
                )
                await self.client.create_collection(
                    collection_name=self.config.collection_name,
                    vectors_config={
                        "dense": qmodels.VectorParams(
                            size=self.config.vector_size,
                            distance=qdistance,
                        )
                    },
                    sparse_vectors_config={
                        "sparse": qmodels.SparseVectorParams(
                            index=qmodels.SparseIndexParams(on_disk=False)
                        )
                    },
                )
            else:
                logger.info(
                    f"Creating Standard Qdrant collection '{self.config.collection_name}' "
                    f"({self.config.vector_size}d dense)"
                )
                await self.client.create_collection(
                    collection_name=self.config.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.config.vector_size,
                        distance=qdistance,
                    ),
                )

            await self._create_payload_indexes()

    async def _create_payload_indexes(self) -> None:
        """Create schema indexes on fields frequently used for query filtering."""
        fields_to_index = [
            ("document_id", qmodels.PayloadSchemaType.KEYWORD),
            ("file_name", qmodels.PayloadSchemaType.KEYWORD),
            ("layout_type", qmodels.PayloadSchemaType.KEYWORD),
            ("page_number", qmodels.PayloadSchemaType.INTEGER),
            ("token_count", qmodels.PayloadSchemaType.INTEGER),
        ]

        for field_name, schema_type in fields_to_index:
            try:
                await self.client.create_payload_index(
                    collection_name=self.config.collection_name,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except Exception as e:
                logger.warning(f"Failed to create index for '{field_name}': {e}")

    async def upsert_chunks(self, chunks: list[DocumentChunk], hybrid: bool = True) -> bool:
        """Upsert document chunks into Qdrant using dense or dual dense+sparse vectors."""
        if not chunks:
            return True

        try:
            texts = [chunk.content for chunk in chunks]
            dense_vectors = await self.embedding_manager.embed_documents(texts)

            if hybrid:
                sparse_embeddings = list(self.sparse_encoder.embed(texts))
                points = []

                for chunk, dense_vec, sparse_obj in zip(chunks, dense_vectors, sparse_embeddings):
                    qdrant_sparse = qmodels.SparseVector(
                        indices=sparse_obj.indices.tolist(),
                        values=sparse_obj.values.tolist(),
                    )
                    points.append(
                        qmodels.PointStruct(
                            id=chunk.chunk_id,
                            vector={"dense": dense_vec, "sparse": qdrant_sparse},
                            payload=self._build_payload(chunk),
                        )
                    )
            else:
                points = [
                    qmodels.PointStruct(
                        id=chunk.chunk_id,
                        vector=dense_vec,
                        payload=self._build_payload(chunk),
                    )
                    for chunk, dense_vec in zip(chunks, dense_vectors)
                ]

            # Upsert in configured batch sizes
            for i in range(0, len(points), self.config.batch_size):
                batch = points[i : i + self.config.batch_size]
                await self.client.upsert(
                    collection_name=self.config.collection_name,
                    points=batch,
                )
            return True

        except Exception as e:
            logger.error(f"Failed to upsert chunks: {e}")
            return False

    @staticmethod
    def _build_payload(chunk: DocumentChunk) -> dict[str, Any]:
        return {
            "document_id": chunk.document_id,
            "file_name": chunk.file_name,
            "content": chunk.content,
            "chunk_index": chunk.chunk_index,
            "token_count": chunk.token_count,
            "page_number": chunk.page_number,
            "section_header": chunk.section_header,
            "layout_type": chunk.layout_type,
            "metadata": chunk.metadata,
        }

    def _build_filter(
        self,
        file_name_filter: str | None = None,
        layout_type_filter: str | None = None,
        document_id_filter: str | None = None,
        custom_filter: qmodels.Filter | None = None,
    ) -> qmodels.Filter | None:
        must_conditions = []
        if file_name_filter:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="file_name", match=qmodels.MatchValue(value=file_name_filter)
                )
            )
        if layout_type_filter:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="layout_type", match=qmodels.MatchValue(value=layout_type_filter)
                )
            )
        if document_id_filter:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="document_id", match=qmodels.MatchValue(value=document_id_filter)
                )
            )

        if custom_filter:
            if must_conditions:
                custom_filter.must = (custom_filter.must or []) + must_conditions
            return custom_filter

        return qmodels.Filter(must=must_conditions) if must_conditions else None

    async def search_similar(
        self,
        query: str,
        limit: int = 5,
        score_threshold: float | None = None,
        file_name_filter: str | None = None,
        layout_type_filter: str | None = None,
        document_id_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Dense-only vector search."""
        query_vector = await self.embedding_manager.embed_query(query)
        query_filter = self._build_filter(
            file_name_filter, layout_type_filter, document_id_filter
        )

        try:
            search_results = await self.client.search(
                collection_name=self.config.collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )

            return [
                {
                    "score": hit.score,
                    "chunk_id": str(hit.id),
                    "page_content": hit.payload.get("content", ""),
                    "metadata": hit.payload,
                }
                for hit in search_results
            ]
        except Exception as e:
            logger.error(f"Standard search failed: {e}")
            return []

    async def search_hybrid_rrf(
        self,
        query: str,
        limit: int = 5,
        prefetch_limit: int = 20,
        file_name_filter: str | None = None,
        layout_type_filter: str | None = None,
        document_id_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid Search fusing dense and sparse embeddings using Reciprocal Rank Fusion (RRF)."""
        dense_query = await self.embedding_manager.embed_query(query)

        sparse_obj = list(self.sparse_encoder.embed([query]))[0]
        qdrant_sparse_query = qmodels.SparseVector(
            indices=sparse_obj.indices.tolist(),
            values=sparse_obj.values.tolist(),
        )

        query_filter = self._build_filter(
            file_name_filter, layout_type_filter, document_id_filter
        )

        try:
            response = await self.client.query_points(
                collection_name=self.config.collection_name,
                prefetch=[
                    qmodels.Prefetch(
                        query=dense_query,
                        using="dense",
                        filter=query_filter,
                        limit=prefetch_limit,
                    ),
                    qmodels.Prefetch(
                        query=qdrant_sparse_query,
                        using="sparse",
                        filter=query_filter,
                        limit=prefetch_limit,
                    ),
                ],
                query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )

            return [
                {
                    "score": hit.score,
                    "chunk_id": str(hit.id),
                    "page_content": hit.payload.get("content", ""),
                    "metadata": hit.payload,
                }
                for hit in response.points
            ]
        except Exception as e:
            logger.error(f"Hybrid RRF search failed: {e}")
            return []

    async def search_hybrid_weighted(
        self,
        query: str,
        alpha: float = 0.7,
        limit: int = 5,
        file_name_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Client-side MinMax score normalized hybrid search with weighting parameter alpha.
        
        alpha = 1.0 (100% dense), alpha = 0.0 (100% sparse BM25).
        """
        dense_query = await self.embedding_manager.embed_query(query)

        sparse_obj = list(self.sparse_encoder.embed([query]))[0]
        qdrant_sparse = qmodels.SparseVector(
            indices=sparse_obj.indices.tolist(),
            values=sparse_obj.values.tolist(),
        )

        query_filter = self._build_filter(file_name_filter=file_name_filter)
        fetch_limit = limit * 4

        try:
            dense_res = await self.client.search(
                collection_name=self.config.collection_name,
                query_vector=("dense", dense_query),
                query_filter=query_filter,
                limit=fetch_limit,
                with_payload=True,
            )
            sparse_res = await self.client.search(
                collection_name=self.config.collection_name,
                query_vector=("sparse", qdrant_sparse),
                query_filter=query_filter,
                limit=fetch_limit,
                with_payload=True,
            )

            def min_max_normalize(hits):
                if not hits:
                    return {}
                scores = [h.score for h in hits]
                min_s, max_s = min(scores), max(scores)
                if max_s == min_s:
                    return {h.id: 1.0 for h in hits}
                return {h.id: (h.score - min_s) / (max_s - min_s) for h in hits}

            norm_dense = min_max_normalize(dense_res)
            norm_sparse = min_max_normalize(sparse_res)

            payload_map = {h.id: h.payload for h in dense_res + sparse_res}
            all_ids = set(norm_dense.keys()).union(set(norm_sparse.keys()))

            combined_scores = {}
            for pid in all_ids:
                s_dense = norm_dense.get(pid, 0.0)
                s_sparse = norm_sparse.get(pid, 0.0)
                combined_scores[pid] = (alpha * s_dense) + ((1.0 - alpha) * s_sparse)

            sorted_hits = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

            return [
                {
                    "score": score,
                    "chunk_id": str(pid),
                    "page_content": payload_map[pid].get("content", ""),
                    "metadata": payload_map[pid],
                }
                for pid, score in sorted_hits
            ]
        except Exception as e:
            logger.error(f"Weighted hybrid search failed: {e}")
            return []

    async def delete_document_chunks(self, document_id: str) -> bool:
        """Delete all vectors associated with a document_id."""
        try:
            await self.client.delete(
                collection_name=self.config.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=document_id),
                            )
                        ]
                    )
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Failed deleting chunks for doc {document_id}: {e}")
            return False

    async def get_collection_stats(self) -> dict[str, Any]:
        """Fetch status and counts for the target collection."""
        try:
            info = await self.client.get_collection(self.config.collection_name)
            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.name,
            }
        except Exception as e:
            logger.error(f"Failed fetching stats: {e}")
            return {}

    async def scroll_documents(
        self,
        limit: int = 50,
        offset: str | None = None,
        file_name_filter: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Paginate through chunks stored in Qdrant."""
        query_filter = self._build_filter(file_name_filter=file_name_filter)
        try:
            records, next_offset = await self.client.scroll(
                collection_name=self.config.collection_name,
                scroll_filter=query_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            results = [
                {
                    "chunk_id": str(rec.id),
                    "page_content": rec.payload.get("content", ""),
                    "metadata": rec.payload,
                }
                for rec in records
            ]
            return results, str(next_offset) if next_offset else None
        except Exception as e:
            logger.error(f"Scroll documents failed: {e}")
            return [], None
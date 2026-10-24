from __future__ import annotations

from backend.services.retrieval.query_rewriter import (
    QueryRewriter,
)
from backend.services.retrieval.evidence_fusion import (
    EvidenceFusion,
)
from backend.services.retrieval.confidence_service import (
    ConfidenceService,
)


class RetrievalOrchestrator:
    """
    Enterprise reasoning retrieval layer.

    Workflow:

    Query
       ↓
    Query Rewriter
       ↓
    Multi Query Search
       ↓
    Evidence Fusion
       ↓
    Confidence Scoring
    """

    def __init__(
        self,
        retrieval_service,
    ):
        self.retrieval_service = (
            retrieval_service
        )

        self.query_rewriter = (
            QueryRewriter()
        )

        self.fusion = (
            EvidenceFusion()
        )

        self.confidence = (
            ConfidenceService()
        )

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ):

        rewritten = (
            self.query_rewriter.rewrite(
                query
            )
        )

        all_results = []

        for expanded_query in (
            rewritten.rewritten_queries
        ):

            results = await (
                self.retrieval_service.search(
                    expanded_query,
                    top_k=top_k,
                )
            )

            all_results.append(
                results
            )

        merged = self.fusion.merge(
            all_results
        )

        scores = [
            result.get(
                "score",
                0.0,
            )
            for result in merged
        ]

        confidence = (
            self.confidence.calculate(
                scores
            )
        )

        return {
            "query": query,
            "expanded_queries":
                rewritten.rewritten_queries,
            "results": merged[:top_k],
            "confidence":
                confidence.score,
            "confidence_level":
                confidence.level,
        }
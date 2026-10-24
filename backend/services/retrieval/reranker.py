"""
Enterprise Retrieval Reranker

Responsibilities:
- Re-rank retrieved chunks
- Boost exact query matches
- Boost title matches
- Boost metadata matches
- Penalize weak evidence

Future:
- Cross Encoder Re-ranking
- Cohere Re-rank
- BGE Re-ranker
- OpenAI Re-ranking
"""

from __future__ import annotations

import re
from typing import Any


class RetrievalReranker:
    """
    Lightweight reranker using content
    and metadata signals.
    """

    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        query_terms = {
            token.lower()
            for token in re.findall(
                r"\w+",
                query
            )
        }

        ranked_results = []

        for result in results:

            score = float(
                result.get("score", 0.0)
            )

            content = (
                result.get("content", "")
                .lower()
            )

            title = (
                result.get("title", "")
                .lower()
            )

            metadata = (
                result.get("metadata", {})
            )

            rerank_score = score

            # Exact query term matches

            content_hits = sum(
                1
                for term in query_terms
                if term in content
            )

            rerank_score += (
                content_hits * 0.05
            )

            # Title boosts

            title_hits = sum(
                1
                for term in query_terms
                if term in title
            )

            rerank_score += (
                title_hits * 0.15
            )

            # Approved document boost

            if metadata.get(
                "approved",
                True,
            ):
                rerank_score += 0.05

            # Current version boost

            if metadata.get(
                "latest_version",
                True,
            ):
                rerank_score += 0.05

            # Confidence

            result["rerank_score"] = round(
                rerank_score,
                4,
            )

            ranked_results.append(
                result
            )

        ranked_results.sort(
            key=lambda item: item[
                "rerank_score"
            ],
            reverse=True,
        )

        return ranked_results

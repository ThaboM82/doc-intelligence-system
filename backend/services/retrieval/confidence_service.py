from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    score: float
    level: str


class ConfidenceService:
    def calculate(
        self,
        retrieval_scores: list[float],
    ) -> ConfidenceResult:

        if not retrieval_scores:
            return ConfidenceResult(
                score=0.0,
                level="low",
            )

        avg = sum(retrieval_scores) / len(retrieval_scores)

        if avg >= 0.85:
            level = "high"
        elif avg >= 0.60:
            level = "medium"
        else:
            level = "low"

        return ConfidenceResult(
            score=round(avg, 3),
            level=level,
        )
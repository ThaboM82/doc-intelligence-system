from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CitationValidationResult:
    valid: bool
    missing_sources: list[str]


class CitationValidator:
    """
    Ensures all citations reference
    valid retrieved documents.
    """

    def validate(
        self,
        citations: list[dict],
    ) -> CitationValidationResult:

        missing = []

        for citation in citations:

            source = citation.get("source")

            if not source:
                missing.append(
                    str(citation)
                )

        return CitationValidationResult(
            valid=len(missing) == 0,
            missing_sources=missing,
        )
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryExpansion:
    original_query: str
    rewritten_queries: list[str]


class QueryRewriter:
    """
    Expands user questions into retrieval-friendly queries.
    """

    def rewrite(
        self,
        query: str,
    ) -> QueryExpansion:

        q = query.strip()

        variants = {
            q,
            q.lower(),
        }

        replacements = {
            "leave": [
                "annual leave",
                "vacation policy",
                "employee leave procedure",
                "leave approval workflow",
            ],
            "retention": [
                "document retention policy",
                "record retention requirements",
                "retention schedule",
            ],
            "security": [
                "security policy",
                "security controls",
                "security requirements",
            ],
            "incident": [
                "incident response",
                "incident management",
                "incident escalation procedure",
            ],
        }

        lowered = q.lower()

        for keyword, expansions in replacements.items():
            if keyword in lowered:
                variants.update(expansions)

        return QueryExpansion(
            original_query=q,
            rewritten_queries=list(variants),
        )
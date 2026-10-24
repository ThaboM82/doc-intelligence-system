from __future__ import annotations


class EvidenceFusion:
    """
    Merges retrieval results
    from multiple searches.
    """

    def merge(
        self,
        search_results: list[list[dict]],
    ) -> list[dict]:

        seen = set()
        merged = []

        for result_set in search_results:

            for item in result_set:

                chunk_id = item.get(
                    "chunk_id"
                )

                if chunk_id in seen:
                    continue

                seen.add(chunk_id)

                merged.append(item)

        merged.sort(
            key=lambda x: x.get(
                "score",
                0.0,
            ),
            reverse=True,
        )

        return merged
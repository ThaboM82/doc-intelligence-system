"""Score RAG answers against gold expected substrings / sources."""

from __future__ import annotations

from typing import Any


def normalize(s: str) -> str:
    return " ".join((s or "").lower().split())


def answer_hits(answer: str, expected_contains: list[str]) -> list[str]:
    hay = normalize(answer)
    hits: list[str] = []
    for needle in expected_contains:
        n = normalize(str(needle))
        if n and n in hay:
            hits.append(str(needle))
    return hits


def hit_rate(answer: str, expected_contains: list[str]) -> float:
    if not expected_contains:
        return 1.0 if (answer or "").strip() else 0.0
    hits = answer_hits(answer, expected_contains)
    return len(hits) / len(expected_contains)


def source_match(
    sources: list[dict[str, Any]] | None,
    expected_source_doc: str | None = None,
    expected_doc_id: str | None = None,
) -> bool:
    if not sources or (not expected_source_doc and not expected_doc_id):
        return False
    for s in sources:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or s.get("doc_id") or "")
        title = str(
            s.get("title")
            or s.get("source_file")
            or s.get("file_name")
            or ""
        )
        payload = s.get("payload") if isinstance(s.get("payload"), dict) else {}
        blob = " ".join(
            [
                sid,
                title,
                str(payload.get("doc_id") or ""),
                str(payload.get("source_file") or ""),
                str(payload.get("chunk_id") or ""),
            ]
        ).lower()
        if expected_doc_id and expected_doc_id.lower() in blob:
            return True
        if expected_source_doc and expected_source_doc.lower() in blob:
            return True
    return False


def score_item(
    *,
    answer: str,
    expected_contains: list[str],
    sources: list[dict[str, Any]] | None = None,
    expected_source_doc: str | None = None,
    expected_doc_id: str | None = None,
    require_source: bool = False,
    min_hit_rate: float = 0.0,
) -> dict[str, Any]:
    hits = answer_hits(answer, expected_contains)
    rate = hit_rate(answer, expected_contains)

    if expected_contains:
        passed = rate > 0 and rate >= min_hit_rate
        # default: any hit is enough unless min_hit_rate raised
        if min_hit_rate <= 0:
            passed = len(hits) > 0
    else:
        passed = bool((answer or "").strip())

    src_ok: bool | None = None
    if expected_source_doc or expected_doc_id:
        src_ok = source_match(sources, expected_source_doc, expected_doc_id)
        if require_source and not src_ok:
            passed = False

    return {
        "passed": passed,
        "hits": hits,
        "hit_rate": round(rate, 4),
        "source_match": src_ok,
        "answer_len": len(answer or ""),
        "num_sources": len(sources or []),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    errors = sum(1 for r in results if r.get("error"))
    src_checked = [r for r in results if r.get("source_match") is not None]
    src_ok = sum(1 for r in src_checked if r.get("source_match"))
    latencies = [
        float(r["latency_ms"])
        for r in results
        if isinstance(r.get("latency_ms"), (int, float))
    ]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
    hit_rates = [
        float(r["hit_rate"])
        for r in results
        if isinstance(r.get("hit_rate"), (int, float))
    ]
    avg_hit_rate = round(sum(hit_rates) / len(hit_rates), 4) if hit_rates else 0.0

    by_difficulty: dict[str, dict[str, int]] = {}
    for r in results:
        d = str(r.get("difficulty") or "unknown")
        bucket = by_difficulty.setdefault(d, {"total": 0, "passed": 0})
        bucket["total"] += 1
        if r.get("passed"):
            bucket["passed"] += 1

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "errors": errors,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "avg_hit_rate": avg_hit_rate,
        "source_checked": len(src_checked),
        "source_matched": src_ok,
        "avg_latency_ms": avg_latency,
        "by_difficulty": by_difficulty,
    }


def format_table(results: list[dict[str, Any]]) -> str:
    lines = [
        f"{'ID':<8} {'PASS':<6} {'HITS':<28} {'LAT(ms)':<10} QUESTION",
        "-" * 88,
    ]
    for r in results:
        pid = str(r.get("id", ""))[:8]
        ok = "Y" if r.get("passed") else ("ERR" if r.get("error") else "N")
        hits = ",".join(r.get("hits") or [])[:28]
        lat = r.get("latency_ms")
        lat_s = f"{lat:.0f}" if isinstance(lat, (int, float)) else "-"
        q = str(r.get("question") or "")[:40]
        lines.append(f"{pid:<8} {ok:<6} {hits:<28} {lat_s:<10} {q}")
    return "\n".join(lines)
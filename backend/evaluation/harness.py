"""
Run RAG eval against the live API.

Env:
  API_BASE or VITE_API_URL  (default http://localhost:8000)

Usage:
  python -m backend.evaluation.harness
  python backend/evaluation/harness.py --base-url https://YOUR-API.onrender.com
  python backend/evaluation/harness.py --require-source --min-hit-rate 0.5
  python backend/evaluation/harness.py --difficulty easy --out last_run.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.evaluation.dataset import filter_eval_set, load_eval_set
from backend.evaluation.metrics import format_table, score_item, summarize


def query_rag(
    base_url: str,
    question: str,
    top_k: int = 5,
    timeout: float = 90.0,
    retries: int = 2,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/v1/rag/query"
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, json={"query": question, "top_k": top_k})
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
                continue
            raise last_err
    raise RuntimeError("unreachable")


def run_eval(
    base_url: str,
    *,
    top_k: int = 5,
    require_source: bool = False,
    min_hit_rate: float = 0.0,
    difficulty: str | None = None,
    ids: list[str] | None = None,
    retries: int = 2,
) -> list[dict[str, Any]]:
    items = filter_eval_set(
        load_eval_set(), difficulty=difficulty, ids=ids
    )
    results: list[dict[str, Any]] = []
    print(f"API: {base_url}")
    print(f"Questions: {len(items)}  top_k={top_k}  retries={retries}\n")

    for row in items:
        qid = row["id"]
        question = row["question"]
        print(f"[{qid}] {question}")
        t0 = time.perf_counter()
        try:
            data = query_rag(
                base_url, question, top_k=top_k, retries=retries
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            answer = str(data.get("answer") or data.get("result") or "")
            sources = (
                data.get("sources")
                if isinstance(data.get("sources"), list)
                else []
            )
            # Prefer server-reported latency if present
            server_lat = data.get("processing_time_ms")
            if isinstance(server_lat, (int, float)):
                latency_ms = float(server_lat)

            scored = score_item(
                answer=answer,
                expected_contains=row.get("expected_answer_contains") or [],
                sources=sources,
                expected_source_doc=row.get("expected_source_doc"),
                expected_doc_id=row.get("expected_doc_id"),
                require_source=require_source,
                min_hit_rate=min_hit_rate,
            )
            status = "PASS" if scored["passed"] else "FAIL"
            print(
                f"  → {status}  hit_rate={scored['hit_rate']}  "
                f"hits={scored['hits']!r}  {latency_ms}ms"
            )
            if scored["source_match"] is not None:
                print(f"  → source_match={scored['source_match']}")
            results.append(
                {
                    "id": qid,
                    "question": question,
                    "difficulty": row.get("difficulty"),
                    "answer": answer,
                    "latency_ms": latency_ms,
                    **scored,
                }
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            print(f"  → ERROR {exc}")
            results.append(
                {
                    "id": qid,
                    "question": question,
                    "difficulty": row.get("difficulty"),
                    "answer": "",
                    "passed": False,
                    "hits": [],
                    "hit_rate": 0.0,
                    "source_match": None,
                    "latency_ms": latency_ms,
                    "error": str(exc),
                }
            )
        print()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG evaluation harness")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE")
        or os.getenv("VITE_API_URL")
        or "http://localhost:8000",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--require-source",
        action="store_true",
        help="Fail if expected source doc/id not in returned sources",
    )
    parser.add_argument(
        "--min-hit-rate",
        type=float,
        default=0.0,
        help="Require this fraction of expected needles (0 = any hit)",
    )
    parser.add_argument("--difficulty", default=None, help="Filter: easy|medium|...")
    parser.add_argument(
        "--ids",
        default=None,
        help="Comma-separated question ids, e.g. q01,q02",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit 1 if accuracy < this value (e.g. 0.5)",
    )
    args = parser.parse_args()

    ids = [x.strip() for x in args.ids.split(",") if x.strip()] if args.ids else None

    results = run_eval(
        args.base_url,
        top_k=args.top_k,
        require_source=args.require_source,
        min_hit_rate=args.min_hit_rate,
        difficulty=args.difficulty,
        ids=ids,
        retries=args.retries,
    )
    summary = summarize(results)

    print(format_table(results))
    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))

    if args.out:
        payload = {"summary": summary, "results": results}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.out}")

    if summary["total"] and summary["passed"] == 0:
        sys.exit(1)
    if args.fail_under is not None and summary["accuracy"] < args.fail_under:
        print(
            f"Accuracy {summary['accuracy']} < fail-under {args.fail_under}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
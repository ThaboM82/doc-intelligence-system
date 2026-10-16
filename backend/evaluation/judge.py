"""
LLM-as-judge quality gate using RAGAS.

Runs each golden-set question against the live API, collects the retrieved
contexts, and scores faithfulness + answer relevancy with a judge model.

Usage (local):
  OPENAI_API_KEY=... python -m backend.evaluation.judge \
      --base-url http://localhost:8000 --out judge_results.json

Usage (CI gate):
  python -m backend.evaluation.judge \
      --base-url "$API_BASE" \
      --min-faithfulness 0.80 \
      --min-relevancy 0.70 \
      --out judge_results.json --summary-out judge_summary.md

Exits 0 = pass, 1 = gate failure.
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


def query_rag(
    base_url: str, question: str, top_k: int = 5, timeout: float = 90.0
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/v1/rag/query"
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json={"query": question, "top_k": top_k})
        r.raise_for_status()
        return r.json()


def run_judge_eval(
    base_url: str,
    *,
    top_k: int = 5,
    judge_model: str = "gpt-4o-mini",
    difficulty: str | None = None,
    ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from datasets import Dataset  # datasets==5.0.1 already in requirements
    from langchain_openai import ChatOpenAI  # langchain-openai already in requirements
    from ragas import evaluate as ragas_evaluate
    from ragas.metrics import AnswerRelevancy, Faithfulness

    items = filter_eval_set(load_eval_set(), difficulty=difficulty, ids=ids)
    print(f"Judging {len(items)} questions (judge={judge_model})...")

    # 1) Query the API and build the RAGAS dataset
    rows: list[dict[str, Any]] = []
    for row in items:
        t0 = time.perf_counter()
        data = query_rag(base_url, row["question"], top_k=top_k)
        contexts = [
            (s.get("text") or "").strip()
            for s in (data.get("sources") or [])
            if isinstance(s, dict) and (s.get("text") or "").strip()
        ][:8]  # cap contexts for judge cost
        rows.append(
            {
                "id": row["id"],
                "question": row["question"],
                "answer": str(data.get("answer") or ""),
                "contexts": contexts,
                # Faithfulness/relevancy don't need ground truth, but RAGAS
                # wants the column present; fall back to expected needles.
                "ground_truth": " ".join(row.get("expected_answer_contains") or []),
            }
        )
        print(f"  [{row['id']}] {time.perf_counter() - t0:.1f}s, {len(contexts)} contexts")

    if not rows:
        raise SystemExit("No eval items matched the filters.")

    dataset = Dataset.from_list(
        [{k: v for k, v in r.items() if k != "id"} for r in rows]
    )

    # 2) Run the judge
    judge = ChatOpenAI(model=judge_model, temperature=0)
    result = ragas_evaluate(
        dataset,
        metrics=[Faithfulness(llm=judge), AnswerRelevancy(llm=judge)],
    )

    # 3) Merge scores back with ids
    scores = result.to_pandas()
    per_item: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        per_item.append(
            {
                "id": r["id"],
                "question": r["question"],
                "faithfulness": round(float(scores.iloc[i]["faithfulness"]), 4),
                "answer_relevancy": round(float(scores.iloc[i]["answer_relevancy"]), 4),
                "num_contexts": len(r["contexts"]),
            }
        )

    summary = {
        "n": len(per_item),
        "mean_faithfulness": round(sum(p["faithfulness"] for p in per_item) / len(per_item), 4),
        "mean_answer_relevancy": round(sum(p["answer_relevancy"] for p in per_item) / len(per_item), 4),
        "min_faithfulness": min(p["faithfulness"] for p in per_item),
        "judge_model": judge_model,
    }
    return per_item, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="RAGAS judge gate")
    ap.add_argument("--base-url", default=os.getenv("API_BASE") or "http://localhost:8000")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--judge-model", default=os.getenv("JUDGE_MODEL", "gpt-4o-mini"))
    ap.add_argument("--difficulty", default=None)
    ap.add_argument("--ids", default=None)
    ap.add_argument("--min-faithfulness", type=float, default=0.80)
    ap.add_argument("--min-relevancy", type=float, default=0.70)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--summary-out", type=Path, default=None)
    args = ap.parse_args()

    ids = [x.strip() for x in args.ids.split(",") if x.strip()] if args.ids else None

    per_item, summary = run_judge_eval(
        args.base_url, top_k=args.top_k, judge_model=args.judge_model,
        difficulty=args.difficulty, ids=ids,
    )

    print(json.dumps(summary, indent=2))

    failures: list[str] = []
    if summary["mean_faithfulness"] < args.min_faithfulness:
        failures.append(
            f"mean faithfulness {summary['mean_faithfulness']} < {args.min_faithfulness}"
        )
    if summary["mean_answer_relevancy"] < args.min_relevancy:
        failures.append(
            f"mean answer relevancy {summary['mean_answer_relevancy']} < {args.min_relevancy}"
        )

    report_lines = [
        "### RAGAS judge gate",
        "",
        f"| metric | value | threshold |",
        f"|---|---|---|",
        f"| mean faithfulness | {summary['mean_faithfulness']} | >= {args.min_faithfulness} |",
        f"| mean answer relevancy | {summary['mean_answer_relevancy']} | >= {args.min_relevancy} |",
        f"| worst faithfulness | {summary['min_faithfulness']} | |",
        "",
    ]
    report_lines += [f"- ❌ {f}" for f in failures] or ["- ✅ judge gate passed"]
    report = "\n".join(report_lines)
    print(report)

    if args.out:
        args.out.write_text(
            json.dumps({"summary": summary, "per_item": per_item}, indent=2),
            encoding="utf-8",
        )
    if args.summary_out:
        args.summary_out.write_text(report, encoding="utf-8")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
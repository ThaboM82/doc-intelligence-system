#!/usr/bin/env python3
"""
RAG evaluation CLI for Document Intelligence.

Usage (from repo root, venv active):

  set API_BASE=https://doc-intelligence-system-8ase.onrender.com
  python evals/run_evals.py

  python evals/run_evals.py --out backend/data/eval_set/last_run.json
  python evals/run_evals.py --difficulty easy --fail-under 0.3
  python evals/run_evals.py --ids case_001,case_002
  python evals/run_evals.py --in-process

Env:
  API_BASE          Default http://localhost:8000
  EVAL_FAIL_UNDER   Default 0.0 (no gate)
  EVAL_TIMEOUT_SEC  Default 60
  OPENAI_API_KEY    Required only for --in-process path that hits real LLM
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Paths — allow `python evals/run_evals.py` from repo root
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_DATASET = _REPO_ROOT / "backend" / "data" / "eval_set" / "cases.json"
FALLBACK_DATASET = _REPO_ROOT / "backend" / "evaluation" / "cases.json"
DEFAULT_OUT = _REPO_ROOT / "backend" / "data" / "eval_set" / "last_run.json"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

@dataclass
class EvalCase:
    id: str
    query: str
    difficulty: str = "medium"  # easy | medium | hard
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    expect_sources: bool = True
    notes: str = ""


def _read_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text)


def load_cases(path: Path | None = None) -> list[EvalCase]:
    p = path
    if p is None:
        if DEFAULT_DATASET.is_file():
            p = DEFAULT_DATASET
        elif FALLBACK_DATASET.is_file():
            p = FALLBACK_DATASET
        else:
            # Built-in minimal set so the CLI always runs
            return [
                EvalCase(
                    id="builtin_001",
                    query="What is this system used for?",
                    difficulty="easy",
                    must_include=["document"],
                    expect_sources=False,
                    notes="Smoke case when no dataset file exists",
                ),
            ]

    raw = _read_json(p)
    items = raw if isinstance(raw, list) else raw.get("cases") or raw.get("items") or []
    cases: list[EvalCase] = []
    for i, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        q = (row.get("query") or row.get("question") or "").strip()
        if not q:
            continue
        cases.append(
            EvalCase(
                id=str(row.get("id") or f"case_{i+1:03d}"),
                query=q,
                difficulty=str(row.get("difficulty") or "medium").lower(),
                must_include=list(row.get("must_include") or row.get("expected_keywords") or []),
                must_not_include=list(row.get("must_not_include") or []),
                expect_sources=bool(row.get("expect_sources", True)),
                notes=str(row.get("notes") or ""),
            )
        )
    return cases


def filter_cases(
    cases: list[EvalCase],
    *,
    difficulty: str | None,
    ids: set[str] | None,
) -> list[EvalCase]:
    out = cases
    if difficulty:
        d = difficulty.lower()
        out = [c for c in out if c.difficulty == d]
    if ids:
        out = [c for c in out if c.id in ids]
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    id: str
    query: str
    difficulty: str
    passed: bool
    score: float
    latency_ms: float
    answer_preview: str
    sources_count: int
    reasons: list[str] = field(default_factory=list)
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def score_answer(case: EvalCase, answer: str, sources: list[Any]) -> tuple[float, list[str], bool]:
    reasons: list[str] = []
    score = 0.0
    text = (answer or "").strip()
    lower = text.lower()

    if not text:
        return 0.0, ["empty answer"], False

    # Non-empty answer
    score += 0.25
    reasons.append("non_empty_answer")

    # Keyword coverage
    must = [m for m in case.must_include if m]
    if must:
        hits = sum(1 for m in must if m.lower() in lower)
        frac = hits / len(must)
        score += 0.45 * frac
        reasons.append(f"keyword_hits={hits}/{len(must)}")
    else:
        score += 0.20
        reasons.append("no_keyword_constraints")

    # Forbidden terms
    bad = [m for m in case.must_not_include if m and m.lower() in lower]
    if bad:
        score -= 0.25
        reasons.append(f"forbidden={bad}")

    # Sources
    n_src = len(sources or [])
    if case.expect_sources:
        if n_src > 0:
            score += 0.30
            reasons.append(f"sources={n_src}")
        else:
            reasons.append("missing_sources")
    else:
        score += 0.15
        reasons.append("sources_optional")

    score = max(0.0, min(1.0, round(score, 4)))
    passed = score >= 0.5 and not bad
    return score, reasons, passed


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def _http_rag(api_base: str, query: str, top_k: int, timeout: float) -> dict[str, Any]:
    base = api_base.rstrip("/")
    url = f"{base}/api/v1/rag/query"
    body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _in_process_rag(query: str, top_k: int) -> dict[str, Any]:
    """Call service layer directly (no HTTP)."""
    import asyncio
    from backend.services.rag_service import run_rag

    result = asyncio.run(run_rag(query=query, top_k=top_k))
    sources = []
    for s in getattr(result, "sources", []) or []:
        sources.append(
            {
                "id": getattr(s, "id", None),
                "file_name": getattr(s, "file_name", None),
                "score": getattr(s, "score", None),
                "text": (getattr(s, "text", None) or "")[:200],
            }
        )
    return {
        "answer": getattr(result, "answer", "") or "",
        "sources": sources,
        "confidence_score": getattr(result, "confidence_score", None),
        "processing_time_ms": getattr(result, "processing_time_ms", None),
    }


def run_case(
    case: EvalCase,
    *,
    api_base: str,
    top_k: int,
    timeout: float,
    in_process: bool,
) -> CaseResult:
    t0 = time.perf_counter()
    try:
        if in_process:
            data = _in_process_rag(case.query, top_k)
        else:
            data = _http_rag(api_base, case.query, top_k, timeout)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        answer = (
            data.get("answer")
            or data.get("result")
            or data.get("response")
            or ""
        )
        sources = data.get("sources") or data.get("citations") or []
        if not isinstance(sources, list):
            sources = []
        score, reasons, passed = score_answer(case, str(answer), sources)
        return CaseResult(
            id=case.id,
            query=case.query,
            difficulty=case.difficulty,
            passed=passed,
            score=score,
            latency_ms=latency_ms,
            answer_preview=str(answer)[:300],
            sources_count=len(sources),
            reasons=reasons,
            raw={"confidence": data.get("confidence_score")},
        )
    except HTTPError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return CaseResult(
            id=case.id,
            query=case.query,
            difficulty=case.difficulty,
            passed=False,
            score=0.0,
            latency_ms=latency_ms,
            answer_preview="",
            sources_count=0,
            reasons=[],
            error=f"HTTP {exc.code}: {detail}",
        )
    except (URLError, TimeoutError, OSError, Exception) as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return CaseResult(
            id=case.id,
            query=case.query,
            difficulty=case.difficulty,
            passed=False,
            score=0.0,
            latency_ms=latency_ms,
            answer_preview="",
            sources_count=0,
            reasons=[],
            error=str(exc),
        )


def run_eval(
    cases: list[EvalCase],
    *,
    api_base: str,
    top_k: int,
    timeout: float,
    in_process: bool,
) -> dict[str, Any]:
    results: list[CaseResult] = []
    for case in cases:
        print(f"  → {case.id} ({case.difficulty}): {case.query[:60]}...")
        r = run_case(
            case,
            api_base=api_base,
            top_k=top_k,
            timeout=timeout,
            in_process=in_process,
        )
        results.append(r)
        status = "PASS" if r.passed else "FAIL"
        err = f" err={r.error}" if r.error else ""
        print(f"    {status} score={r.score:.2f} latency_ms={r.latency_ms}{err}")

    n = len(results) or 1
    avg_score = sum(r.score for r in results) / n
    pass_rate = sum(1 for r in results if r.passed) / n
    avg_latency = sum(r.latency_ms for r in results) / n

    return {
        "api_base": api_base if not in_process else "in-process",
        "count": len(results),
        "avg_score": round(avg_score, 4),
        "pass_rate": round(pass_rate, 4),
        "avg_latency_ms": round(avg_latency, 2),
        "results": [asdict(r) for r in results],
        "ts": time.time(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAG evaluation suite")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help=f"JSON cases file (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--api-base",
        default=os.getenv("API_BASE", "http://localhost:8000"),
        help="API base URL",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("EVAL_TIMEOUT_SEC", "60")),
    )
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=None)
    parser.add_argument("--ids", default=None, help="Comma-separated case ids")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=float(os.getenv("EVAL_FAIL_UNDER", "0")),
        help="Exit 1 if avg_score < this value",
    )
    parser.add_argument("--out", type=Path, default=None, help="Write JSON report path")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Call backend.services.rag_service.run_rag instead of HTTP",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.dataset)
    id_set = {x.strip() for x in (args.ids or "").split(",") if x.strip()} or None
    cases = filter_cases(cases, difficulty=args.difficulty, ids=id_set)

    if not cases:
        print("No eval cases matched filters.", file=sys.stderr)
        return 2

    print(f"Running {len(cases)} case(s) against {args.api_base if not args.in_process else 'in-process'}")
    report = run_eval(
        cases,
        api_base=args.api_base,
        top_k=args.top_k,
        timeout=args.timeout,
        in_process=args.in_process,
    )

    print("\n=== Summary ===")
    print(f"avg_score={report['avg_score']:.4f}  pass_rate={report['pass_rate']:.4f}  avg_latency_ms={report['avg_latency_ms']}")

    out = args.out or DEFAULT_OUT
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
    except OSError as exc:
        print(f"Could not write report: {exc}", file=sys.stderr)

    if report["avg_score"] < args.fail_under:
        print(
            f"FAIL: avg_score {report['avg_score']:.4f} < fail-under {args.fail_under}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
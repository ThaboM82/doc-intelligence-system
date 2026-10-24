"""
backend.evals.run_evals
───────────────────────
Package entrypoint for evaluation so tests can:

    from backend.evals.run_evals import run_evaluation_suite

Implementation preference
-------------------------
1. Prefer the full CLI module at repo-root ``evals/run_evals.py``
   (load_cases, run_eval, scoring, HTTP / in-process runners).
2. If that file is missing, fall back to a small built-in dry-run suite
   so imports and unit tests never break collection.

Also exposes:
  run_evaluation_suite(...)  — stable API for tests / CI
  load_cases, run_eval, run_case, main, EvalCase, CaseResult — re-exported when available
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "evals" / "run_evals.py"

# Populated when CLI module loads successfully
_cli: Any = None
load_cases: Any = None
run_eval: Any = None
run_case: Any = None
main: Any = None
EvalCase: Any = None
CaseResult: Any = None
filter_cases: Any = None
score_answer: Any = None


def _load_cli_module() -> Any | None:
    """Import repo-root evals/run_evals.py by path (not installed as a package)."""
    global _cli, load_cases, run_eval, run_case, main
    global EvalCase, CaseResult, filter_cases, score_answer

    if _cli is not None:
        return _cli

    if not _CLI_PATH.is_file():
        logger.debug("evals CLI not found at %s — using built-in fallback", _CLI_PATH)
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            "doc_intel_evals_cli_run_evals",
            _CLI_PATH,
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Ensure repo root on path for CLI internal imports
        root = str(_REPO_ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _cli = mod
        load_cases = getattr(mod, "load_cases", None)
        run_eval = getattr(mod, "run_eval", None)
        run_case = getattr(mod, "run_case", None)
        main = getattr(mod, "main", None)
        EvalCase = getattr(mod, "EvalCase", None)
        CaseResult = getattr(mod, "CaseResult", None)
        filter_cases = getattr(mod, "filter_cases", None)
        score_answer = getattr(mod, "score_answer", None)
        return mod
    except Exception as exc:
        logger.warning("Failed to load %s: %s", _CLI_PATH, exc)
        return None


_load_cli_module()


# ---------------------------------------------------------------------------
# Built-in fallback types / helpers (when CLI is absent)
# ---------------------------------------------------------------------------


@dataclass
class _FallbackCase:
    id: str
    query: str
    difficulty: str = "medium"
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    expect_sources: bool = True
    notes: str = ""


def _fallback_load_cases(path: Path | None = None) -> list[Any]:
    candidates = [
        path,
        _REPO_ROOT / "backend" / "data" / "eval_set" / "cases.json",
        _REPO_ROOT / "backend" / "evaluation" / "cases.json",
    ]
    for p in candidates:
        if p is None or not Path(p).is_file():
            continue
        try:
            text = Path(p).read_text(encoding="utf-8-sig")
            raw = json.loads(text)
            items = raw if isinstance(raw, list) else (raw.get("cases") or raw.get("items") or [])
            out: list[Any] = []
            for i, row in enumerate(items):
                if not isinstance(row, dict):
                    continue
                q = (row.get("query") or row.get("question") or "").strip()
                if not q:
                    continue
                out.append(
                    _FallbackCase(
                        id=str(row.get("id") or f"case_{i+1:03d}"),
                        query=q,
                        difficulty=str(row.get("difficulty") or "medium").lower(),
                        must_include=list(
                            row.get("must_include") or row.get("expected_keywords") or []
                        ),
                        must_not_include=list(row.get("must_not_include") or []),
                        expect_sources=bool(row.get("expect_sources", True)),
                        notes=str(row.get("notes") or ""),
                    )
                )
            if out:
                return out
        except Exception as exc:
            logger.debug("fallback load_cases failed for %s: %s", p, exc)

    return [
        _FallbackCase(
            id="builtin_001",
            query="What is this system used for?",
            difficulty="easy",
            must_include=["document"],
            expect_sources=False,
            notes="Smoke case when no dataset file exists",
        )
    ]


def _as_case_id(case: Any) -> str | None:
    return getattr(case, "id", None) if not isinstance(case, dict) else case.get("id")


def _as_case_query(case: Any) -> str | None:
    if isinstance(case, dict):
        return case.get("query") or case.get("question")
    return getattr(case, "query", None)


def _as_case_difficulty(case: Any) -> str:
    if isinstance(case, dict):
        return str(case.get("difficulty") or "medium").lower()
    return str(getattr(case, "difficulty", "medium") or "medium").lower()


def _filter(
    cases: Iterable[Any],
    *,
    difficulty: str | None,
    ids: set[str] | None,
    limit: int | None,
) -> list[Any]:
    out = list(cases)
    if difficulty:
        d = difficulty.lower()
        out = [c for c in out if _as_case_difficulty(c) == d]
    if ids:
        out = [c for c in out if str(_as_case_id(c) or "") in ids]
    if limit is not None:
        out = out[: max(0, int(limit))]
    return out


def _case_to_dict(case: Any) -> dict[str, Any]:
    if is_dataclass(case):
        return asdict(case)
    if isinstance(case, dict):
        return dict(case)
    return {
        "id": _as_case_id(case),
        "query": _as_case_query(case),
        "difficulty": _as_case_difficulty(case),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_evaluation_suite(
    *,
    api_base: str | None = None,
    cases_path: str | Path | None = None,
    difficulty: str | None = None,
    ids: str | list[str] | None = None,
    limit: int | None = None,
    top_k: int = 5,
    timeout: float | None = None,
    dry_run: bool = True,
    in_process: bool = False,
    fail_under: float | None = None,
    out: str | Path | None = None,
) -> dict[str, Any]:
    """
    Stable evaluation entrypoint for tests and CI.

    Parameters
    ----------
    dry_run:
        If True (default), load/filter cases and return a structured report
        without calling the API or LLM.
    in_process:
        When dry_run is False, prefer in-process rag_service if CLI supports it.
    fail_under:
        Optional gate; included in the report (caller decides process exit).
    out:
        Optional path to write JSON report.
    """
    t0 = time.perf_counter()
    base = (
        api_base
        or os.getenv("API_BASE")
        or os.getenv("EVAL_API_BASE")
        or "http://localhost:8000"
    ).rstrip("/")
    timeout_sec = float(
        timeout if timeout is not None else os.getenv("EVAL_TIMEOUT_SEC", "60")
    )

    id_set: set[str] | None = None
    if isinstance(ids, str) and ids.strip():
        id_set = {x.strip() for x in ids.split(",") if x.strip()}
    elif isinstance(ids, list) and ids:
        id_set = {str(x).strip() for x in ids if str(x).strip()}

    path = Path(cases_path) if cases_path else None

    # Load cases via CLI or fallback
    if load_cases is not None:
        try:
            cases = load_cases(path)
        except Exception as exc:
            logger.warning("CLI load_cases failed: %s — using fallback", exc)
            cases = _fallback_load_cases(path)
    else:
        cases = _fallback_load_cases(path)

    if filter_cases is not None and (difficulty or id_set):
        try:
            cases = filter_cases(cases, difficulty=difficulty, ids=id_set)
        except TypeError:
            cases = _filter(cases, difficulty=difficulty, ids=id_set, limit=None)
    else:
        cases = _filter(cases, difficulty=difficulty, ids=id_set, limit=None)

    if limit is not None:
        cases = cases[: max(0, int(limit))]

    # Dry-run: no network / no LLM
    if dry_run or run_eval is None:
        results = [
            {
                "id": _as_case_id(c),
                "query": _as_case_query(c),
                "difficulty": _as_case_difficulty(c),
                "status": "skipped",
                "passed": None,
                "score": None,
                "detail": "dry_run",
            }
            for c in cases
        ]
        report: dict[str, Any] = {
            "api_base": base,
            "dry_run": True,
            "in_process": False,
            "total": len(cases),
            "count": len(cases),
            "passed": 0,
            "failed": 0,
            "skipped": len(cases),
            "avg_score": 0.0,
            "pass_rate": 0.0,
            "avg_latency_ms": 0.0,
            "fail_under": fail_under,
            "results": results,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "ts": time.time(),
        }
        _maybe_write(out, report)
        return report

    # Live path via CLI run_eval
    try:
        report = run_eval(
            cases,
            api_base=base,
            top_k=int(top_k),
            timeout=timeout_sec,
            in_process=bool(in_process),
        )
    except Exception as exc:
        logger.exception("run_eval failed")
        return {
            "api_base": base,
            "dry_run": False,
            "error": str(exc),
            "total": len(cases),
            "passed": 0,
            "failed": len(cases),
            "skipped": 0,
            "results": [],
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    # Normalize shape for tests
    results_raw = report.get("results") or []
    passed = sum(
        1
        for r in results_raw
        if (r.get("passed") is True)
        or str(r.get("status", "")).lower() == "passed"
    )
    failed = sum(
        1
        for r in results_raw
        if (r.get("passed") is False)
        or str(r.get("status", "")).lower() in {"failed", "error"}
    )
    normalized = {
        **report,
        "api_base": report.get("api_base") or base,
        "dry_run": False,
        "in_process": bool(in_process),
        "total": report.get("count") or len(results_raw),
        "passed": passed,
        "failed": failed,
        "skipped": max(
            0,
            (report.get("count") or len(results_raw)) - passed - failed,
        ),
        "fail_under": fail_under,
        "gate_ok": (
            None
            if fail_under is None
            else float(report.get("avg_score") or 0.0) >= float(fail_under)
        ),
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
    _maybe_write(out, normalized)
    return normalized


def _maybe_write(out: str | Path | None, report: dict[str, Any]) -> None:
    if not out:
        return
    try:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write eval report to %s: %s", out, exc)


def cli_available() -> bool:
    """True when repo-root evals/run_evals.py loaded successfully."""
    return _cli is not None and run_eval is not None


def dataset_paths() -> dict[str, str]:
    """Paths the suite probes for case JSON (diagnostics)."""
    return {
        "repo_root": str(_REPO_ROOT),
        "cli": str(_CLI_PATH),
        "cli_exists": str(_CLI_PATH.is_file()),
        "default_dataset": str(
            _REPO_ROOT / "backend" / "data" / "eval_set" / "cases.json"
        ),
        "fallback_dataset": str(
            _REPO_ROOT / "backend" / "evaluation" / "cases.json"
        ),
    }


__all__ = [
    "run_evaluation_suite",
    "cli_available",
    "dataset_paths",
    "load_cases",
    "run_eval",
    "run_case",
    "main",
    "EvalCase",
    "CaseResult",
    "filter_cases",
    "score_answer",
]
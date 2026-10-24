from __future__ import annotations
from typing import Any

def run_evaluation_suite(**kwargs: Any) -> dict[str, Any]:
    """Minimal stub so tests can import; expand later to wrap evals/run_evals.py."""
    return {
        "dry_run": True,
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "results": [],
    }

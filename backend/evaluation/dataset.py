"""Load gold RAG questions from backend/data/eval_set/questions.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

DEFAULT_EVAL_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "eval_set" / "questions.json"
)


def load_eval_set(path: Path | str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path else DEFAULT_EVAL_PATH
    if not p.is_file():
        raise FileNotFoundError(f"Eval set not found: {p}")

    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("questions.json must be a JSON array")

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        q = (item.get("question") or "").strip()
        if not q:
            continue
        needles = item.get("expected_answer_contains") or []
        if isinstance(needles, str):
            needles = [needles]
        rows.append(
            {
                "id": str(item.get("id") or f"q{i + 1:02d}"),
                "question": q,
                "expected_answer_contains": [str(n) for n in needles],
                "expected_source_doc": item.get("expected_source_doc"),
                "expected_doc_id": item.get("expected_doc_id"),
                "difficulty": item.get("difficulty") or "unknown",
                "tags": list(item.get("tags") or []),
            }
        )
    return rows


def filter_eval_set(
    rows: list[dict[str, Any]],
    *,
    difficulty: str | None = None,
    ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    out = rows
    if difficulty:
        d = difficulty.lower()
        out = [r for r in out if str(r.get("difficulty", "")).lower() == d]
    if ids:
        id_set = set(ids)
        out = [r for r in out if r["id"] in id_set]
    return out


def iter_questions(path: Path | str | None = None) -> Iterator[dict[str, Any]]:
    yield from load_eval_set(path)


if __name__ == "__main__":
    items = load_eval_set()
    print(f"Loaded {len(items)} questions from {DEFAULT_EVAL_PATH}")
    by_diff: dict[str, int] = {}
    for row in items:
        d = str(row.get("difficulty") or "unknown")
        by_diff[d] = by_diff.get(d, 0) + 1
    print("By difficulty:", by_diff)
    for row in items[:3]:
        print(f"  - {row['id']}: {row['question'][:70]}...")
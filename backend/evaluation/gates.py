"""
Regression gates: compare a fresh eval run against a baseline.

Usage (CI):
  python -m backend.evaluation.gates \
      --new eval_results.json \
      --baseline backend/data/eval_set/baseline.json \
      --min-accuracy 0.70 \
      --max-accuracy-drop 0.05 \
      --max-p95-ms 12000

Exits 0 = pass, 1 = gate failure. Also writes a markdown summary for the
GitHub Actions step summary.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (works on small eval sets)."""
    if not values:
        return None
    vals = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(vals)))
    return round(vals[rank - 1], 2)


def latency_stats(results: list[dict]) -> dict[str, float | None]:
    lat = [float(r["latency_ms"]) for r in results if isinstance(r.get("latency_ms"), (int, float))]
    return {
        "n": len(lat),
        "p50_ms": percentile(lat, 50),
        "p95_ms": percentile(lat, 95),
        "avg_ms": round(sum(lat) / len(lat), 2) if lat else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True, help="JSON from harness --out")
    ap.add_argument("--baseline", default=None, help="Baseline JSON (same format)")
    ap.add_argument("--min-accuracy", type=float, default=0.70)
    ap.add_argument("--max-accuracy-drop", type=float, default=0.05,
                    help="Max allowed accuracy drop vs baseline (absolute)")
    ap.add_argument("--max-p95-ms", type=float, default=12_000.0)
    ap.add_argument("--summary-out", type=Path, default=None)
    args = ap.parse_args()

    payload = json.loads(Path(args.new).read_text(encoding="utf-8"))
    results = payload["results"]
    summary = payload["summary"]
    lat = latency_stats(results)

    failures: list[str] = []

    acc = summary["accuracy"]
    if acc < args.min_accuracy:
        failures.append(f"accuracy {acc} < min {args.min_accuracy}")

    baseline_summary = None
    if args.baseline and Path(args.baseline).is_file():
        base_payload = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        baseline_summary = base_payload.get("summary")
        if baseline_summary:
            drop = baseline_summary["accuracy"] - acc
            if drop > args.max_accuracy_drop:
                failures.append(
                    f"accuracy dropped {drop:.3f} vs baseline "
                    f"({baseline_summary['accuracy']} -> {acc}), "
                    f"max allowed {args.max_accuracy_drop}"
                )

    if lat["p95_ms"] is not None and lat["p95_ms"] > args.max_p95_ms:
        failures.append(f"p95 latency {lat['p95_ms']}ms > {args.max_p95_ms}ms")

    if summary.get("errors", 0) > 0:
        failures.append(f"{summary['errors']} eval request(s) errored")

    lines = [
        "### RAG regression gate",
        "",
        "| metric | this run | baseline |",
        "|---|---|---|",
        f"| accuracy | {acc} | {baseline_summary['accuracy'] if baseline_summary else 'n/a'} |",
        f"| p50 latency | {lat['p50_ms']}ms | |",
        f"| p95 latency | {lat['p95_ms']}ms | |",
        f"| source match | {summary.get('source_matched')}/{summary.get('source_checked')} | |",
        "",
    ]
    lines += [f"- ❌ {f}" for f in failures] or ["- ✅ all gates passed"]

    report = "\n".join(lines)
    print(report)
    if args.summary_out:
        args.summary_out.write_text(report, encoding="utf-8")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
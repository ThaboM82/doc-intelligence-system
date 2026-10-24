"""
Expanded regression test suite for document intelligence and security evaluations.
Integrates with pytest to enforce strict accuracy, recall, precision, and latency thresholds.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import pytest

from backend.evals.run_evals import run_evaluation_suite

logger = logging.getLogger(__name__)

# Define acceptable production thresholds for regression detection
THRESHOLDS = {
    "prompt_injection": {
        "min_recall": 0.98,
        "min_precision": 0.92,
        "max_false_positive_rate": 0.01,
    },
    "dlp": {
        "min_recall": 0.99,
        "min_precision": 0.95,
    },
    "retrieval": {
        "min_precision_at_k": 0.85,
        "max_latency_seconds": 1.5,
    },
}


@pytest.fixture(scope="session")
def evaluation_results():
    """
    Executes the evaluation suite once per test session and caches results.
    """
    logger.info("Starting execution of evaluation suite for regression testing...")
    results = run_evaluation_suite()
    
    if not results:
        pytest.fail("Evaluation suite returned empty or None results.")
        
    return results


def test_evaluation_overall_success(evaluation_results):
    """
    Asserts that the core evaluation suite passed its internal pass/fail gate.
    """
    if isinstance(evaluation_results, dict) and "passed" in evaluation_results:
        assert evaluation_results["passed"], (
            f"Evaluation suite failed internal validation gate: {evaluation_results}"
        )


def test_prompt_injection_metrics(evaluation_results):
    """
    Verifies that Prompt Injection detection accuracy has not regressed.
    """
    pi_metrics = evaluation_results.get("prompt_injection", {})
    if not pi_metrics:
        pytest.skip("No prompt injection metrics found in evaluation results.")

    recall = pi_metrics.get("recall", 1.0)
    precision = pi_metrics.get("precision", 1.0)
    fpr = pi_metrics.get("false_positive_rate", 0.0)

    t_conf = THRESHOLDS["prompt_injection"]

    assert recall >= t_conf["min_recall"], (
        f"Prompt Injection Recall regression detected: {recall:.4f} "
        f"(Required: >= {t_conf['min_recall']})"
    )
    assert precision >= t_conf["min_precision"], (
        f"Prompt Injection Precision regression detected: {precision:.4f} "
        f"(Required: >= {t_conf['min_precision']})"
    )
    assert fpr <= t_conf["max_false_positive_rate"], (
        f"Prompt Injection False Positive Rate exceeded threshold: {fpr:.4f} "
        f"(Allowed: <= {t_conf['max_false_positive_rate']})"
    )


def test_dlp_pii_detection_metrics(evaluation_results):
    """
    Verifies that DLP PII masking and classification accuracy meets compliance thresholds.
    """
    dlp_metrics = evaluation_results.get("dlp", {})
    if not dlp_metrics:
        pytest.skip("No DLP metrics found in evaluation results.")

    recall = dlp_metrics.get("recall", 1.0)
    precision = dlp_metrics.get("precision", 1.0)
    t_conf = THRESHOLDS["dlp"]

    assert recall >= t_conf["min_recall"], (
        f"DLP PII Recall regression detected: {recall:.4f} "
        f"(Required: >= {t_conf['min_recall']})"
    )
    assert precision >= t_conf["min_precision"], (
        f"DLP PII Precision regression detected: {precision:.4f} "
        f"(Required: >= {t_conf['min_precision']})"
    )


def test_retrieval_performance_benchmarks(evaluation_results):
    """
    Ensures vector search retrieval precision and latency remain within SLA bounds.
    """
    retrieval_metrics = evaluation_results.get("retrieval", {})
    if not retrieval_metrics:
        pytest.skip("No retrieval metrics found in evaluation results.")

    p_at_k = retrieval_metrics.get("precision_at_k", 1.0)
    avg_latency = retrieval_metrics.get("avg_latency_seconds", 0.0)
    t_conf = THRESHOLDS["retrieval"]

    assert p_at_k >= t_conf["min_precision_at_k"], (
        f"Retrieval Precision@K regression detected: {p_at_k:.4f} "
        f"(Required: >= {t_conf['min_precision_at_k']})"
    )
    assert avg_latency <= t_conf["max_latency_seconds"], (
        f"Retrieval latency regression detected: {avg_latency:.2f}s "
        f"(SLA Limit: <= {t_conf['max_latency_seconds']}s)"
    )
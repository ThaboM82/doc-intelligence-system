"""
Advanced and comprehensive unit test suite for administrative routes,
security headers, telemetry, error resilience, and edge cases in the
Document Intelligence backend.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.intelligence import set_active_llm_factory

client = TestClient(app)


def test_security_and_telemetry_headers():
    """Verify that all responses include required security headers and process-time telemetry."""
    response = client.get("/health")
    assert response.status_code == 200
    
    # Check security headers
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    
    # Check telemetry header
    assert "X-Process-Time-Ms" in response.headers


def test_uninitialized_llm_factory_error():
    """Ensure that calling intelligence endpoints when the LLM factory is None raises a 500 error."""
    # Temporarily unset the active factory
    set_active_llm_factory(None)

    payload = {
        "query": "What is the document about?",
        "query_vector": [0.1] * 1536,
        "top_k": 3
    }

    response = client.post("/api/v1/intelligence/query", json=payload)
    assert response.status_code == 500
    assert "LLM Factory has not been initialized" in response.json()["detail"]


@patch("backend.routers.intelligence.upsert_documents", new_callable=AsyncMock)
def test_ingest_database_failure_resilience(mock_upsert):
    """Test that Qdrant connection errors during ingestion return a clean 500 HTTP exception."""
    mock_upsert.side_effect = Exception("Qdrant cluster unavailable")

    payload = {
        "documents": [
            {
                "text": "Failing test chunk.",
                "vector": [0.1] * 1536,
                "metadata": {"source": "fail.pdf"}
            }
        ]
    }

    response = client.post("/api/v1/intelligence/ingest", json=payload)
    assert response.status_code == 500
    assert "Failed to ingest documents" in response.json()["detail"]


def test_invalid_query_payload_validation():
    """Verify that malformed or out-of-range query parameters trigger Pydantic validation errors (422)."""
    # top_k must be between 1 and 20; passing 99 should fail validation.
    payload = {
        "query": "Invalid top_k test",
        "query_vector": [0.1] * 1536,
        "top_k": 99
    }

    response = client.post("/api/v1/intelligence/query", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
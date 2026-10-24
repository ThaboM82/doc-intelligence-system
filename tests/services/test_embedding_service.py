from __future__ import annotations

import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

# Add the repository root so the backend package can be imported when pytest
# is launched from outside the project directory.
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.services.embeddings.embedding_service import (  # type: ignore[reportMissingImports]
    EmbeddingService,
    EmbeddingServiceError,
)


@pytest.fixture
def embedding_service():
    """Fixture providing a configured EmbeddingService instance for unit testing."""
    return EmbeddingService(
        model_name="text-embedding-3-small",
        batch_size=2,
        max_concurrent=2,
        max_retries=2,
        initial_backoff=0.01  # Fast backoff for rapid test execution
    )


@pytest.mark.asyncio
async def test_generate_embeddings_success(embedding_service):
    """Test successful batch embedding generation with correct vector structure."""
    mock_response = AsyncMock()
    mock_response.data = [
        AsyncMock(embedding=[0.1, 0.2, 0.3]),
        AsyncMock(embedding=[0.4, 0.5, 0.6]),
    ]
    mock_response.usage.total_tokens = 45

    mock_client = AsyncMock()
    mock_client.embeddings.create.return_value = mock_response

    with patch("backend.services.embeddings.embedding_service.OpenAIProvider.get_client", return_value=mock_client):
        texts = ["Document chunk one", "Document chunk two"]
        embeddings = await embedding_service.generate_embeddings(texts)

        assert len(embeddings) == 2
        assert embeddings[0] == [0.1, 0.2, 0.3]
        assert embeddings[1] == [0.4, 0.5, 0.6]
        mock_client.embeddings.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_single_embedding(embedding_service):
    """Test generating a single vector embedding for search queries or quick ingestion."""
    mock_response = AsyncMock()
    mock_response.data = [AsyncMock(embedding=[0.9, 0.8, 0.7])]
    mock_response.usage.total_tokens = 12

    mock_client = AsyncMock()
    mock_client.embeddings.create.return_value = mock_response

    with patch("backend.services.embeddings.embedding_service.OpenAIProvider.get_client", return_value=mock_client):
        embedding = await embedding_service.generate_single_embedding("Single query text")

        assert embedding == [0.9, 0.8, 0.7]
        assert len(embedding) == 3


@pytest.mark.asyncio
async def test_generate_embeddings_empty_input(embedding_service):
    """Test that passing an empty list returns an empty list without calling the API."""
    with patch("backend.services.embeddings.embedding_service.OpenAIProvider.get_client") as mock_get_client:
        embeddings = await embedding_service.generate_embeddings([])
        
        assert embeddings == []
        mock_get_client.assert_not_called()


@pytest.mark.asyncio
async def test_sanitize_texts(embedding_service):
    """Test robust handling of whitespace, empty values, and non-string types."""
    raw_texts = ["  Secure policy text  ", "", None, "   ", 456]  # type: ignore
    
    # Normalize inputs as done internally
    formatted_inputs = [str(t) if t is not None else "" for t in raw_texts]
    sanitized = embedding_service._sanitize_texts(formatted_inputs)
    
    assert sanitized[0] == "Secure policy text"
    assert sanitized[1] == ""
    assert sanitized[2] == ""
    assert sanitized[3] == ""
    assert sanitized[4] == "456"


@pytest.mark.asyncio
async def test_retry_on_transient_failure(embedding_service):
    """Test that transient API errors trigger exponential backoff retries before succeeding."""
    mock_success_response = AsyncMock()
    mock_success_response.data = [AsyncMock(embedding=[0.1, 0.2])]
    mock_success_response.usage.total_tokens = 15

    mock_client = AsyncMock()
    # Fail twice with transient exceptions, succeed on the third attempt
    mock_client.embeddings.create.side_effect = [
        Exception("Rate limit 429"),
        Exception("Gateway timeout 504"),
        mock_success_response
    ]

    with patch("backend.services.embeddings.embedding_service.OpenAIProvider.get_client", return_value=mock_client):
        embeddings = await embedding_service.generate_embeddings(["Retry test chunk"])

        assert len(embeddings) == 2
        assert mock_client.embeddings.create.call_count == 3


@pytest.mark.asyncio
async def test_max_retries_exceeded_raises_error(embedding_service):
    """Test that exhausting all retry attempts raises a custom EmbeddingServiceError."""
    mock_client = AsyncMock()
    mock_client.embeddings.create.side_effect = Exception("Persistent upstream failure")

    with patch("backend.services.embeddings.embedding_service.OpenAIProvider.get_client", return_value=mock_client):
        with pytest.raises(EmbeddingServiceError) as exc_info:
            await embedding_service.generate_embeddings(["Failing chunk"])

        assert "Failed to generate embeddings after 2 retries" in str(exc_info.value)
        assert mock_client.embeddings.create.call_count == 2


@pytest.mark.asyncio
async def test_single_embedding_failure_raises_error(embedding_service):
    """Test that failure in single embedding helper propagates the service error."""
    mock_client = AsyncMock()
    mock_client.embeddings.create.side_effect = Exception("API down")

    with patch("backend.services.embeddings.embedding_service.OpenAIProvider.get_client", return_value=mock_client):
        with pytest.raises(EmbeddingServiceError):
            await embedding_service.generate_single_embedding("Failing single query")
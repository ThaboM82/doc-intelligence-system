"""Unit tests for AzureBlobStorageProvider (mocked container client)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.observability.storage_provider import AzureBlobStorageProvider


class _FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readall(self) -> bytes:
        return self._data


@pytest.fixture
def container_client() -> MagicMock:
    cc = MagicMock()
    store: dict[str, bytes] = {}

    def upload_blob(*, name: str, data: bytes, overwrite: bool = True, **_: Any) -> None:
        store[name] = data if isinstance(data, (bytes, bytearray)) else bytes(data)

    def download_blob(name: str, **_: Any) -> _FakeDownloader:
        if name not in store:
            raise type("BlobNotFound", (Exception,), {})()
        return _FakeDownloader(store[name])

    def get_blob_client(name: str) -> MagicMock:
        blob = MagicMock()
        blob.exists.return_value = name in store
        return blob

    def delete_blob(name: str, **_: Any) -> None:
        store.pop(name, None)

    cc.upload_blob.side_effect = upload_blob
    cc.download_blob.side_effect = download_blob
    cc.get_blob_client.side_effect = get_blob_client
    cc.delete_blob.side_effect = delete_blob
    cc._store = store  # type: ignore[attr-defined]
    return cc


@pytest.fixture
def provider(container_client: MagicMock) -> AzureBlobStorageProvider:
    return AzureBlobStorageProvider(
        container="test-container",
        container_client=container_client,
    )


@pytest.mark.asyncio
async def test_azure_write_read_json(provider: AzureBlobStorageProvider) -> None:
    await provider.write_json("cost.json", {"usd": 0.01})
    assert (await provider.read_json("cost.json"))["usd"] == 0.01


@pytest.mark.asyncio
async def test_azure_missing(provider: AzureBlobStorageProvider) -> None:
    assert await provider.read_bytes("missing.bin") is None
    assert await provider.exists("missing.bin") is False


@pytest.mark.asyncio
async def test_azure_delete(provider: AzureBlobStorageProvider) -> None:
    await provider.write_text("t.txt", "x") if hasattr(provider, "write_text") else await provider.write_bytes(
        "t.txt", b"x"
    )
    # write via bytes path
    await provider.write_bytes("t.txt", b"x")
    assert await provider.exists("t.txt") is True
    assert await provider.delete("t.txt") is True
    assert await provider.exists("t.txt") is False
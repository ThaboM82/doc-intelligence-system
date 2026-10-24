"""Unit tests for S3StorageProvider (mocked boto client)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.observability.storage_provider import S3StorageProvider


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.fixture
def s3_client() -> MagicMock:
    client = MagicMock()
    store: dict[str, bytes] = {}

    def put_object(*, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:
        store[Key] = Body if isinstance(Body, (bytes, bytearray)) else bytes(Body)

    def get_object(*, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:
        if Key not in store:
            exc = type("NoSuchKey", (Exception,), {})()
            raise exc
        return {"Body": _FakeBody(store[Key])}

    def head_object(*, Bucket: str, Key: str, **_: Any) -> dict[str, str]:
        if Key not in store:
            raise Exception("404")
        return {"ContentLength": str(len(store[Key]))}

    def delete_object(*, Bucket: str, Key: str, **_: Any) -> None:
        store.pop(Key, None)

    client.put_object.side_effect = put_object
    client.get_object.side_effect = get_object
    client.head_object.side_effect = head_object
    client.delete_object.side_effect = delete_object
    client._store = store  # type: ignore[attr-defined]
    return client


@pytest.fixture
def provider(s3_client: MagicMock) -> S3StorageProvider:
    return S3StorageProvider(bucket="test-bucket", prefix="obs", client=s3_client)


@pytest.mark.asyncio
async def test_s3_write_read_json(provider: S3StorageProvider) -> None:
    await provider.write_json("metrics.json", {"ok": True})
    data = await provider.read_json("metrics.json")
    assert data == {"ok": True}


@pytest.mark.asyncio
async def test_s3_missing(provider: S3StorageProvider) -> None:
    assert await provider.read_json("nope.json") is None
    assert await provider.exists("nope.json") is False


@pytest.mark.asyncio
async def test_s3_exists_delete(provider: S3StorageProvider) -> None:
    await provider.write_bytes("a.bin", b"abc")
    assert await provider.exists("a.bin") is True
    assert await provider.delete("a.bin") is True
    assert await provider.exists("a.bin") is False


@pytest.mark.asyncio
async def test_s3_prefix_applied(provider: S3StorageProvider, s3_client: MagicMock) -> None:
    await provider.write_json("x.json", {"a": 1})
    # key should be obs/x.json
    assert "obs/x.json" in s3_client._store
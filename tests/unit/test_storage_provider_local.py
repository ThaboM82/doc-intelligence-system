"""
Unit tests for LocalStorageProvider (filesystem JSON / bytes / text).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.observability.storage_provider import LocalStorageProvider


@pytest.fixture
def provider(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path))


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_write_read_json(provider: LocalStorageProvider) -> None:
    await provider.write_json("test.json", {"hello": "world"})
    result = await provider.read_json("test.json")
    assert result["hello"] == "world"


@pytest.mark.asyncio
async def test_write_json_nested_path(provider: LocalStorageProvider, tmp_path: Path) -> None:
    await provider.write_json("nested/dir/data.json", {"n": 1})
    assert (tmp_path / "nested" / "dir" / "data.json").is_file()
    data = await provider.read_json("nested/dir/data.json")
    assert data["n"] == 1


@pytest.mark.asyncio
async def test_read_json_missing_returns_none_or_raises(
    provider: LocalStorageProvider,
) -> None:
    """Provider may return None or raise FileNotFoundError — accept either."""
    try:
        result = await provider.read_json("missing.json")
        assert result is None
    except FileNotFoundError:
        pass


@pytest.mark.asyncio
async def test_write_json_overwrite(provider: LocalStorageProvider) -> None:
    await provider.write_json("x.json", {"v": 1})
    await provider.write_json("x.json", {"v": 2})
    assert (await provider.read_json("x.json"))["v"] == 2


@pytest.mark.asyncio
async def test_write_json_list_payload(provider: LocalStorageProvider) -> None:
    await provider.write_json("arr.json", [1, 2, 3])
    assert await provider.read_json("arr.json") == [1, 2, 3]


# ---------------------------------------------------------------------------
# Text / bytes (if implemented)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_read_text(provider: LocalStorageProvider) -> None:
    if not hasattr(provider, "write_text"):
        pytest.skip("write_text not implemented")
    await provider.write_text("note.txt", "hello")
    assert await provider.read_text("note.txt") == "hello"


@pytest.mark.asyncio
async def test_write_read_bytes(provider: LocalStorageProvider) -> None:
    if not hasattr(provider, "write_bytes"):
        pytest.skip("write_bytes not implemented")
    payload = b"\x00\x01\x02"
    await provider.write_bytes("bin.dat", payload)
    assert await provider.read_bytes("bin.dat") == payload


# ---------------------------------------------------------------------------
# Exists / delete / list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exists(provider: LocalStorageProvider) -> None:
    if not hasattr(provider, "exists"):
        pytest.skip("exists not implemented")
    assert await provider.exists("nope.json") is False
    await provider.write_json("yes.json", {})
    assert await provider.exists("yes.json") is True


@pytest.mark.asyncio
async def test_delete(provider: LocalStorageProvider) -> None:
    if not hasattr(provider, "delete"):
        pytest.skip("delete not implemented")
    await provider.write_json("gone.json", {"a": 1})
    assert await provider.delete("gone.json") is True
    try:
        result = await provider.read_json("gone.json")
        assert result is None
    except FileNotFoundError:
        pass


@pytest.mark.asyncio
async def test_list_keys(provider: LocalStorageProvider) -> None:
    if not hasattr(provider, "list_keys"):
        pytest.skip("list_keys not implemented")
    await provider.write_json("a.json", {"a": 1})
    await provider.write_json("b.json", {"b": 2})
    keys = await provider.list_keys()
    assert "a.json" in keys
    assert "b.json" in keys


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_traversal_rejected(provider: LocalStorageProvider) -> None:
    """Relative paths must stay under root."""
    with pytest.raises((ValueError, OSError)):
        await provider.write_json("../outside.json", {"x": 1})


@pytest.mark.asyncio
async def test_root_property(provider: LocalStorageProvider, tmp_path: Path) -> None:
    root = getattr(provider, "root", None) or getattr(provider, "base_dir", None)
    if root is None:
        pytest.skip("no root attribute")
    assert Path(root).resolve() == tmp_path.resolve()
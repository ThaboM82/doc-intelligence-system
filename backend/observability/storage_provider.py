"""
Observability storage provider

1) Event streams (metrics / security / HITL side data)
   - InMemoryObservabilityStore | FileObservabilityStore | RedisObservabilityStore
   - Env: OBS_STORAGE_BACKEND=memory|redis|file

2) Object / file providers (artifacts, admin exports, tests)
   - LocalStorageProvider | S3StorageProvider | AzureBlobStorageProvider
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None  # type: ignore


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ===========================================================================
# Event stream stores
# ===========================================================================


class ObservabilityStore(ABC):
    """Minimal append + list + stats interface for ops telemetry."""

    @abstractmethod
    def append(self, stream: str, event: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def list(
        self,
        stream: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ...

    @abstractmethod
    def stats(self, stream: str | None = None) -> dict[str, Any]:
        ...

    @abstractmethod
    def clear(self, stream: str | None = None) -> int:
        ...


class InMemoryObservabilityStore(ObservabilityStore):
    def __init__(self, max_events: int | None = None) -> None:
        self._max = max_events or _env_int("OBS_STORAGE_MAX_EVENTS", 2000)
        self._lock = Lock()
        self._streams: dict[str, deque[dict[str, Any]]] = {}

    def _q(self, stream: str) -> deque[dict[str, Any]]:
        if stream not in self._streams:
            self._streams[stream] = deque(maxlen=self._max)
        return self._streams[stream]

    def append(self, stream: str, event: dict[str, Any]) -> dict[str, Any]:
        row = dict(event)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("ts", time.time())
        with self._lock:
            self._q(stream).append(row)
            return dict(row)

    def list(
        self,
        stream: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = list(self._q(stream))
        rows.reverse()
        total = len(rows)
        page = [dict(r) for r in rows[offset : offset + max(1, limit)]]
        return page, total

    def stats(self, stream: str | None = None) -> dict[str, Any]:
        with self._lock:
            if stream:
                return {
                    "stream": stream,
                    "count": len(self._q(stream)),
                    "max": self._max,
                }
            return {
                "streams": {k: len(v) for k, v in self._streams.items()},
                "max_per_stream": self._max,
            }

    def clear(self, stream: str | None = None) -> int:
        with self._lock:
            if stream:
                n = len(self._streams.get(stream, ()))
                self._streams.pop(stream, None)
                return n
            n = sum(len(v) for v in self._streams.values())
            self._streams.clear()
            return n


class FileObservabilityStore(ObservabilityStore):
    def __init__(self, path: str | None = None, max_events: int | None = None) -> None:
        self._path = Path(
            path or os.getenv("OBS_FILE_PATH", "backend/data/obs_store.json")
        )
        self._max = max_events or _env_int("OBS_STORAGE_MAX_EVENTS", 2000)
        self._lock = Lock()
        self._streams: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._streams = {
                        str(k): list(v)[-self._max :]
                        for k, v in data.items()
                        if isinstance(v, list)
                    }
        except Exception as exc:
            logger.warning("obs file load failed: %s", exc)
            self._streams = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._streams, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("obs file save failed: %s", exc)

    def append(self, stream: str, event: dict[str, Any]) -> dict[str, Any]:
        row = dict(event)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("ts", time.time())
        with self._lock:
            bucket = self._streams.setdefault(stream, [])
            bucket.append(row)
            if len(bucket) > self._max:
                self._streams[stream] = bucket[-self._max :]
            self._save()
            return dict(row)

    def list(
        self,
        stream: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = list(self._streams.get(stream, []))
        rows.reverse()
        total = len(rows)
        return [dict(r) for r in rows[offset : offset + max(1, limit)]], total

    def stats(self, stream: str | None = None) -> dict[str, Any]:
        with self._lock:
            if stream:
                return {
                    "stream": stream,
                    "count": len(self._streams.get(stream, [])),
                    "path": str(self._path),
                }
            return {
                "streams": {k: len(v) for k, v in self._streams.items()},
                "path": str(self._path),
            }

    def clear(self, stream: str | None = None) -> int:
        with self._lock:
            if stream:
                n = len(self._streams.get(stream, []))
                self._streams.pop(stream, None)
            else:
                n = sum(len(v) for v in self._streams.values())
                self._streams.clear()
            self._save()
            return n


class RedisObservabilityStore(ObservabilityStore):
    def __init__(self) -> None:
        if redis_lib is None:
            raise RuntimeError("redis package not installed")
        url = (
            os.getenv("OBS_REDIS_URL") or os.getenv("HITL_REDIS_URL") or ""
        ).strip()
        if not url:
            raise RuntimeError("OBS_REDIS_URL not set")
        self._prefix = os.getenv("OBS_REDIS_PREFIX", "obs").rstrip(":")
        self._max = _env_int("OBS_STORAGE_MAX_EVENTS", 2000)
        self._r = redis_lib.Redis.from_url(url, decode_responses=True)
        self._r.ping()

    def _key(self, stream: str) -> str:
        return f"{self._prefix}:stream:{stream}"

    def append(self, stream: str, event: dict[str, Any]) -> dict[str, Any]:
        row = dict(event)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("ts", time.time())
        key = self._key(stream)
        pipe = self._r.pipeline()
        pipe.lpush(key, json.dumps(row, default=str))
        pipe.ltrim(key, 0, self._max - 1)
        pipe.execute()
        return row

    def list(
        self,
        stream: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        key = self._key(stream)
        total = int(self._r.llen(key))
        end = offset + max(1, limit) - 1
        raw = self._r.lrange(key, offset, end)
        rows: list[dict[str, Any]] = []
        for item in raw:
            try:
                rows.append(json.loads(item))
            except Exception:
                continue
        return rows, total

    def stats(self, stream: str | None = None) -> dict[str, Any]:
        if stream:
            return {
                "stream": stream,
                "count": int(self._r.llen(self._key(stream))),
            }
        return {"backend": "redis", "prefix": self._prefix}

    def clear(self, stream: str | None = None) -> int:
        if stream:
            key = self._key(stream)
            n = int(self._r.llen(key))
            self._r.delete(key)
            return n
        keys = list(
            self._r.scan_iter(match=f"{self._prefix}:stream:*", count=100)
        )
        n = 0
        if keys:
            for k in keys:
                n += int(self._r.llen(k))
            self._r.delete(*keys)
        return n


_store: ObservabilityStore | None = None
_store_lock = Lock()


def create_obs_store() -> ObservabilityStore:
    backend = (os.getenv("OBS_STORAGE_BACKEND") or "memory").strip().lower()
    if backend == "redis":
        try:
            store = RedisObservabilityStore()
            logger.info("Observability store backend: redis")
            return store
        except Exception as exc:
            logger.warning("Redis obs store failed (%s); using memory", exc)
            return InMemoryObservabilityStore()
    if backend == "file":
        logger.info("Observability store backend: file")
        return FileObservabilityStore()
    logger.debug("Observability store backend: memory")
    return InMemoryObservabilityStore()


def get_obs_store() -> ObservabilityStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = create_obs_store()
    return _store


def set_obs_store(store: ObservabilityStore) -> None:
    global _store
    with _store_lock:
        _store = store


def reset_obs_store() -> InMemoryObservabilityStore:
    fresh = InMemoryObservabilityStore()
    set_obs_store(fresh)
    return fresh


def record_obs_event(stream: str, **fields: Any) -> dict[str, Any]:
    return get_obs_store().append(stream, fields)


# ===========================================================================
# Object / file providers (tests + artifact I/O)
# ===========================================================================


class LocalStorageProvider:
    """Async filesystem storage rooted at ``root``."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self.base_dir = self.root
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative: str) -> Path:
        rel = relative.replace("\\", "/").lstrip("/")
        if ".." in Path(rel).parts:
            raise ValueError(f"Path escapes storage root: {relative}")
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"Path escapes storage root: {relative}")
        return path

    async def write_json(self, relative: str, data: Any) -> None:
        path = self._resolve(relative)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)

    async def read_json(self, relative: str) -> Any | None:
        path = self._resolve(relative)

        def _read() -> Any | None:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

        return await asyncio.to_thread(_read)

    async def write_text(self, relative: str, text: str) -> None:
        path = self._resolve(relative)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        await asyncio.to_thread(_write)

    async def read_text(self, relative: str) -> str | None:
        path = self._resolve(relative)

        def _read() -> str | None:
            if not path.is_file():
                return None
            return path.read_text(encoding="utf-8")

        return await asyncio.to_thread(_read)

    async def write_bytes(self, relative: str, data: bytes) -> None:
        path = self._resolve(relative)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)

    async def read_bytes(self, relative: str) -> bytes | None:
        path = self._resolve(relative)

        def _read() -> bytes | None:
            if not path.is_file():
                return None
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def exists(self, relative: str) -> bool:
        path = self._resolve(relative)
        return await asyncio.to_thread(path.is_file)

    async def delete(self, relative: str) -> bool:
        path = self._resolve(relative)

        def _del() -> bool:
            if not path.is_file():
                return False
            path.unlink()
            return True

        return await asyncio.to_thread(_del)

    async def list_keys(self, prefix: str = "") -> list[str]:
        base = self._resolve(prefix) if prefix else self.root

        def _list() -> list[str]:
            if not base.exists():
                return []
            out: list[str] = []
            for p in base.rglob("*"):
                if p.is_file():
                    out.append(p.relative_to(self.root).as_posix())
            return sorted(out)

        return await asyncio.to_thread(_list)


class S3StorageProvider:
    """S3-compatible object storage (inject ``client`` in tests)."""

    def __init__(
        self,
        bucket: str | None = None,
        prefix: str = "",
        *,
        endpoint_url: str | None = None,
        client: Any = None,
    ) -> None:
        self.bucket = bucket or os.getenv("OBS_S3_BUCKET", "")
        self.prefix = (prefix or os.getenv("OBS_S3_PREFIX", "")).strip("/")
        self._client = client
        self._endpoint_url = endpoint_url or os.getenv("OBS_S3_ENDPOINT_URL")

    def _key(self, relative: str) -> str:
        rel = relative.replace("\\", "/").lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{rel}"
        return rel

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from importlib import import_module

        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        boto3 = import_module("boto3")
        self._client = boto3.client("s3", **kwargs)
        return self._client

    async def write_json(self, relative: str, data: Any) -> None:
        await self.write_bytes(
            relative, json.dumps(data, ensure_ascii=False).encode("utf-8")
        )

    async def read_json(self, relative: str) -> Any | None:
        raw = await self.read_bytes(relative)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    async def write_bytes(self, relative: str, data: bytes) -> None:
        client = self._get_client()
        key = self._key(relative)

        def _put() -> None:
            client.put_object(Bucket=self.bucket, Key=key, Body=data)

        await asyncio.to_thread(_put)

    async def read_bytes(self, relative: str) -> bytes | None:
        client = self._get_client()
        key = self._key(relative)

        def _get() -> bytes | None:
            try:
                resp = client.get_object(Bucket=self.bucket, Key=key)
                return resp["Body"].read()
            except Exception as exc:
                name = type(exc).__name__
                if "NoSuchKey" in name or "404" in str(exc):
                    return None
                raise

        return await asyncio.to_thread(_get)

    async def exists(self, relative: str) -> bool:
        client = self._get_client()
        key = self._key(relative)

        def _head() -> bool:
            try:
                client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_head)

    async def delete(self, relative: str) -> bool:
        client = self._get_client()
        key = self._key(relative)

        def _del() -> bool:
            try:
                client.delete_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_del)


class AzureBlobStorageProvider:
    """Azure Blob storage (inject ``container_client`` in tests)."""

    def __init__(
        self,
        container: str | None = None,
        *,
        connection_string: str | None = None,
        container_client: Any = None,
    ) -> None:
        self.container = container or os.getenv("OBS_AZURE_CONTAINER", "")
        self._connection_string = connection_string or os.getenv(
            "OBS_AZURE_CONNECTION_STRING", ""
        )
        self._container_client = container_client

    def _get_container(self) -> Any:
        if self._container_client is not None:
            return self._container_client
        try:
            blob_sdk = importlib.import_module("azure.storage.blob")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Azure Blob storage requires the optional 'azure-storage-blob' package."
            ) from exc

        svc = blob_sdk.BlobServiceClient.from_connection_string(
            self._connection_string
        )
        self._container_client = svc.get_container_client(self.container)
        return self._container_client

    async def write_json(self, relative: str, data: Any) -> None:
        await self.write_bytes(
            relative, json.dumps(data, ensure_ascii=False).encode("utf-8")
        )

    async def read_json(self, relative: str) -> Any | None:
        raw = await self.read_bytes(relative)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    async def write_bytes(self, relative: str, data: bytes) -> None:
        cc = self._get_container()
        blob = relative.replace("\\", "/").lstrip("/")

        def _upload() -> None:
            cc.upload_blob(name=blob, data=data, overwrite=True)

        await asyncio.to_thread(_upload)

    async def read_bytes(self, relative: str) -> bytes | None:
        cc = self._get_container()
        blob = relative.replace("\\", "/").lstrip("/")

        def _download() -> bytes | None:
            try:
                return cc.download_blob(blob).readall()
            except Exception as exc:
                if "BlobNotFound" in type(exc).__name__ or "404" in str(exc):
                    return None
                raise

        return await asyncio.to_thread(_download)

    async def exists(self, relative: str) -> bool:
        cc = self._get_container()
        blob = relative.replace("\\", "/").lstrip("/")

        def _exists() -> bool:
            return bool(cc.get_blob_client(blob).exists())

        return await asyncio.to_thread(_exists)

    async def delete(self, relative: str) -> bool:
        cc = self._get_container()
        blob = relative.replace("\\", "/").lstrip("/")

        def _del() -> bool:
            try:
                cc.delete_blob(blob)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_del)


# Test-friendly aliases
S3Provider = S3StorageProvider
AzureStorageProvider = AzureBlobStorageProvider
AzureBlobProvider = AzureBlobStorageProvider


__all__ = [
    # streams
    "ObservabilityStore",
    "InMemoryObservabilityStore",
    "FileObservabilityStore",
    "RedisObservabilityStore",
    "create_obs_store",
    "get_obs_store",
    "set_obs_store",
    "reset_obs_store",
    "record_obs_event",
    # objects
    "LocalStorageProvider",
    "S3StorageProvider",
    "AzureBlobStorageProvider",
    "S3Provider",
    "AzureStorageProvider",
    "AzureBlobProvider",
]
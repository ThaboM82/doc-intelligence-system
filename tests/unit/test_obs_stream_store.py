"""
Unit tests for observability event stream stores.

Covers:
  - InMemoryObservabilityStore (append / list / stats / clear / max cap)
  - FileObservabilityStore (persist + reload)
  - RedisObservabilityStore (mocked redis client)
  - Factory / singleton helpers (create_obs_store, get/set/reset, record_obs_event)
  - Edge cases, concurrency, stream isolation
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.observability.storage_provider import (
    FileObservabilityStore,
    InMemoryObservabilityStore,
    RedisObservabilityStore,
    create_obs_store,
    get_obs_store,
    record_obs_event,
    reset_obs_store,
    set_obs_store,
)


# ---------------------------------------------------------------------------
# In-memory
# ---------------------------------------------------------------------------


class TestInMemoryObservabilityStore:
    def test_append_assigns_id_and_ts(self) -> None:
        store = InMemoryObservabilityStore(max_events=50)
        row = store.append("security", {"threat_type": "scan", "severity": "low"})
        assert row.get("threat_type") == "scan"
        assert "id" in row and row["id"]
        assert isinstance(row.get("ts"), (int, float))

    def test_list_newest_first(self) -> None:
        store = InMemoryObservabilityStore(max_events=50)
        store.append("security", {"n": 1})
        store.append("security", {"n": 2})
        store.append("security", {"n": 3})
        rows, total = store.list("security", limit=10)
        assert total == 3
        assert [r["n"] for r in rows] == [3, 2, 1]

    def test_list_pagination(self) -> None:
        store = InMemoryObservabilityStore(max_events=50)
        for i in range(10):
            store.append("sec", {"i": i})
        page, total = store.list("sec", limit=3, offset=0)
        assert total == 10
        assert len(page) == 3
        assert page[0]["i"] == 9
        page2, _ = store.list("sec", limit=3, offset=3)
        assert page2[0]["i"] == 6

    def test_stats_single_and_all(self) -> None:
        store = InMemoryObservabilityStore(max_events=100)
        store.append("a", {"x": 1})
        store.append("b", {"y": 2})
        store.append("b", {"y": 3})
        assert store.stats("a")["count"] == 1
        assert store.stats("b")["count"] == 2
        all_stats = store.stats()
        assert all_stats["streams"]["a"] == 1
        assert all_stats["streams"]["b"] == 2
        assert all_stats["max_per_stream"] == 100

    def test_clear_stream_and_all(self) -> None:
        store = InMemoryObservabilityStore(max_events=50)
        store.append("a", {"x": 1})
        store.append("b", {"y": 2})
        assert store.clear("a") == 1
        assert store.stats("a")["count"] == 0
        assert store.stats("b")["count"] == 1
        assert store.clear() >= 1
        assert store.stats().get("streams") == {}

    def test_max_events_cap(self) -> None:
        store = InMemoryObservabilityStore(max_events=5)
        for i in range(12):
            store.append("cap", {"i": i})
        rows, total = store.list("cap", limit=20)
        assert total == 5
        assert rows[0]["i"] == 11
        assert rows[-1]["i"] == 7

    def test_empty_stream_list(self) -> None:
        store = InMemoryObservabilityStore()
        rows, total = store.list("never", limit=10)
        assert rows == []
        assert total == 0

    def test_append_preserves_explicit_id(self) -> None:
        store = InMemoryObservabilityStore()
        row = store.append("s", {"id": "fixed-id", "v": 1})
        assert row["id"] == "fixed-id"


class TestInMemoryEdgeCases:
    def test_limit_zero_treated_as_one(self) -> None:
        store = InMemoryObservabilityStore()
        store.append("s", {"n": 1})
        store.append("s", {"n": 2})
        rows, total = store.list("s", limit=0, offset=0)
        assert total == 2
        assert len(rows) >= 1

    def test_offset_beyond_length(self) -> None:
        store = InMemoryObservabilityStore()
        store.append("s", {"n": 1})
        rows, total = store.list("s", limit=10, offset=50)
        assert total == 1
        assert rows == []

    def test_multiple_fields_roundtrip(self) -> None:
        store = InMemoryObservabilityStore()
        payload = {
            "threat_type": "prompt_injection",
            "severity": "high",
            "document_id": "doc-1",
            "detail": "blocked pattern",
            "meta": {"path": "/api/v1/rag/query"},
        }
        store.append("security", payload)
        rows, _ = store.list("security", limit=1)
        assert rows[0]["threat_type"] == "prompt_injection"
        assert rows[0]["meta"]["path"] == "/api/v1/rag/query"

    def test_clear_unknown_stream_returns_zero(self) -> None:
        store = InMemoryObservabilityStore()
        assert store.clear("does-not-exist") == 0

    def test_stats_unknown_stream_zero(self) -> None:
        store = InMemoryObservabilityStore()
        assert store.stats("missing")["count"] == 0

    def test_append_does_not_mutate_caller_dict(self) -> None:
        store = InMemoryObservabilityStore()
        original = {"severity": "low"}
        store.append("s", original)
        assert "id" not in original
        assert "ts" not in original


class TestInMemoryConcurrency:
    def test_concurrent_appends(self) -> None:
        store = InMemoryObservabilityStore(max_events=500)

        def worker(n: int) -> None:
            for i in range(20):
                store.append("concurrent", {"worker": n, "i": i})

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker, range(8)))

        _, total = store.list("concurrent", limit=1000)
        assert total == 160


# ---------------------------------------------------------------------------
# File-backed
# ---------------------------------------------------------------------------


class TestFileObservabilityStore:
    def test_persist_and_reload(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.json"
        store = FileObservabilityStore(path=str(path), max_events=50)
        store.append("security", {"threat_type": "ingest", "severity": "low"})
        store.append("security", {"threat_type": "scan", "severity": "high"})
        assert path.is_file()

        reloaded = FileObservabilityStore(path=str(path), max_events=50)
        rows, total = reloaded.list("security", limit=10)
        assert total == 2
        assert rows[0]["threat_type"] == "scan"

    def test_file_clear(self, tmp_path: Path) -> None:
        path = tmp_path / "obs2.json"
        store = FileObservabilityStore(path=str(path), max_events=20)
        store.append("x", {"a": 1})
        assert store.clear("x") == 1
        rows, total = store.list("x")
        assert total == 0

    def test_file_stats_include_path(self, tmp_path: Path) -> None:
        path = tmp_path / "obs3.json"
        store = FileObservabilityStore(path=str(path), max_events=20)
        store.append("s", {"z": 1})
        st = store.stats("s")
        assert st["count"] == 1
        assert "obs3.json" in str(st.get("path", ""))

    def test_file_max_trim(self, tmp_path: Path) -> None:
        path = tmp_path / "obs4.json"
        store = FileObservabilityStore(path=str(path), max_events=3)
        for i in range(6):
            store.append("t", {"i": i})
        _, total = store.list("t", limit=20)
        assert total == 3

    def test_corrupt_file_starts_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not-json", encoding="utf-8")
        store = FileObservabilityStore(path=str(path), max_events=10)
        rows, total = store.list("any")
        assert total == 0
        assert rows == []


class TestFileEdgeCases:
    def test_list_pagination_file(self, tmp_path: Path) -> None:
        path = tmp_path / "page.json"
        store = FileObservabilityStore(path=str(path), max_events=50)
        for i in range(8):
            store.append("p", {"i": i})
        page, total = store.list("p", limit=3, offset=2)
        assert total == 8
        assert len(page) == 3
        assert page[0]["i"] == 5

    def test_reload_after_clear_all(self, tmp_path: Path) -> None:
        path = tmp_path / "clr.json"
        store = FileObservabilityStore(path=str(path), max_events=20)
        store.append("a", {"x": 1})
        store.append("b", {"y": 2})
        assert store.clear() == 2
        reloaded = FileObservabilityStore(path=str(path), max_events=20)
        streams = reloaded.stats().get("streams") or {}
        assert streams == {}

    def test_file_preserves_explicit_ts(self, tmp_path: Path) -> None:
        path = tmp_path / "ts.json"
        store = FileObservabilityStore(path=str(path), max_events=10)
        store.append("s", {"ts": 12345.0, "v": 1})
        rows, _ = store.list("s")
        assert rows[0]["ts"] == 12345.0

    def test_empty_file_json_object(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("{}", encoding="utf-8")
        store = FileObservabilityStore(path=str(path), max_events=10)
        rows, total = store.list("any")
        assert total == 0 and rows == []

    def test_file_parent_dirs_created(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "obs.json"
        store = FileObservabilityStore(path=str(path), max_events=5)
        store.append("s", {"ok": True})
        assert path.is_file()


# ---------------------------------------------------------------------------
# Redis (mocked)
# ---------------------------------------------------------------------------


class TestRedisObservabilityStore:
    def test_redis_append_list(self) -> None:
        fake = MagicMock()
        lists: dict[str, list[str]] = {}

        def lpush(key: str, value: str) -> int:
            lists.setdefault(key, []).insert(0, value)
            return len(lists[key])

        def ltrim(key: str, start: int, end: int) -> bool:
            if key in lists:
                lists[key] = lists[key][start : end + 1]
            return True

        def llen(key: str) -> int:
            return len(lists.get(key, []))

        def lrange(key: str, start: int, end: int) -> list[str]:
            data = lists.get(key, [])
            if end == -1:
                return data[start:]
            return data[start : end + 1]

        def delete(*keys: str) -> int:
            n = 0
            for k in keys:
                if k in lists:
                    n += 1
                    lists.pop(k, None)
            return n

        pipe = MagicMock()
        pipe.lpush.side_effect = lambda k, v: lpush(k, v)
        pipe.ltrim.side_effect = lambda k, s, e: ltrim(k, s, e)
        pipe.execute.return_value = []

        fake.pipeline.return_value = pipe
        fake.llen.side_effect = llen
        fake.lrange.side_effect = lrange
        fake.delete.side_effect = delete
        fake.ping.return_value = True

        with patch.dict(os.environ, {"OBS_REDIS_URL": "redis://localhost:6379/0"}):
            with patch(
                "backend.observability.storage_provider.redis_lib"
            ) as redis_mod:
                redis_mod.Redis.from_url.return_value = fake
                store = RedisObservabilityStore()
                key = store._key("security")
                lpush(key, json.dumps({"id": "1", "ts": 1.0, "threat_type": "x"}))
                rows, total = store.list("security", limit=5)
                assert total >= 1
                assert store.stats("security")["count"] >= 1

    def test_redis_missing_url_raises(self) -> None:
        with patch.dict(os.environ, {"OBS_REDIS_URL": "", "HITL_REDIS_URL": ""}, clear=False):
            os.environ.pop("OBS_REDIS_URL", None)
            os.environ.pop("HITL_REDIS_URL", None)
            with patch("backend.observability.storage_provider.redis_lib") as redis_mod:
                redis_mod.Redis = MagicMock()
                with pytest.raises(RuntimeError, match="OBS_REDIS_URL"):
                    RedisObservabilityStore()


class TestRedisExtra:
    def test_redis_clear_stream(self) -> None:
        fake = MagicMock()
        lists: dict[str, list[str]] = {}

        def llen(key: str) -> int:
            return len(lists.get(key, []))

        def delete(*keys: str) -> int:
            removed = 0
            for k in keys:
                if k in lists:
                    removed += 1
                    del lists[k]
            return removed

        pipe = MagicMock()
        pipe.lpush.return_value = 1
        pipe.ltrim.return_value = True
        pipe.execute.return_value = []

        fake.pipeline.return_value = pipe
        fake.llen.side_effect = llen
        fake.lrange.return_value = []
        fake.delete.side_effect = delete
        fake.ping.return_value = True
        fake.scan_iter.return_value = iter([])

        with patch.dict(os.environ, {"OBS_REDIS_URL": "redis://localhost:6379/0"}):
            with patch(
                "backend.observability.storage_provider.redis_lib"
            ) as redis_mod:
                redis_mod.Redis.from_url.return_value = fake
                store = RedisObservabilityStore()
                key = store._key("security")
                lists[key] = [
                    json.dumps({"id": "1", "ts": 1.0, "threat_type": "a"}),
                    json.dumps({"id": "2", "ts": 2.0, "threat_type": "b"}),
                ]
                n = store.clear("security")
                assert n == 2
                assert key not in lists

    def test_redis_list_skips_bad_json(self) -> None:
        fake = MagicMock()
        fake.ping.return_value = True
        fake.pipeline.return_value = MagicMock(
            lpush=MagicMock(),
            ltrim=MagicMock(),
            execute=MagicMock(return_value=[]),
        )
        fake.llen.return_value = 2
        fake.lrange.return_value = [
            "{bad",
            json.dumps({"id": "ok", "ts": 1.0, "threat_type": "scan"}),
        ]

        with patch.dict(os.environ, {"OBS_REDIS_URL": "redis://localhost:6379/0"}):
            with patch(
                "backend.observability.storage_provider.redis_lib"
            ) as redis_mod:
                redis_mod.Redis.from_url.return_value = fake
                store = RedisObservabilityStore()
                rows, total = store.list("security", limit=10)
                assert total == 2
                assert len(rows) == 1
                assert rows[0]["threat_type"] == "scan"

    def test_redis_stats_global(self) -> None:
        fake = MagicMock()
        fake.ping.return_value = True
        fake.pipeline.return_value = MagicMock(
            lpush=MagicMock(),
            ltrim=MagicMock(),
            execute=MagicMock(return_value=[]),
        )

        with patch.dict(os.environ, {"OBS_REDIS_URL": "redis://localhost:6379/0"}):
            with patch(
                "backend.observability.storage_provider.redis_lib"
            ) as redis_mod:
                redis_mod.Redis.from_url.return_value = fake
                store = RedisObservabilityStore()
                st = store.stats()
                assert st.get("backend") == "redis"
                assert "prefix" in st


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------


class TestFactoryAndSingleton:
    def test_create_default_memory(self) -> None:
        with patch.dict(os.environ, {"OBS_STORAGE_BACKEND": "memory"}):
            store = create_obs_store()
            assert isinstance(store, InMemoryObservabilityStore)

    def test_create_file_backend(self, tmp_path: Path) -> None:
        path = tmp_path / "factory.json"
        with patch.dict(
            os.environ,
            {
                "OBS_STORAGE_BACKEND": "file",
                "OBS_FILE_PATH": str(path),
            },
        ):
            store = create_obs_store()
            assert isinstance(store, FileObservabilityStore)
            store.append("s", {"ok": True})
            assert path.is_file()

    def test_create_redis_falls_back_without_package(self) -> None:
        with patch.dict(
            os.environ,
            {"OBS_STORAGE_BACKEND": "redis", "OBS_REDIS_URL": "redis://localhost/0"},
        ):
            with patch(
                "backend.observability.storage_provider.redis_lib",
                None,
            ):
                store = create_obs_store()
                assert isinstance(store, InMemoryObservabilityStore)

    def test_get_set_reset_singleton(self) -> None:
        reset_obs_store()
        a = get_obs_store()
        b = get_obs_store()
        assert a is b
        custom = InMemoryObservabilityStore(max_events=3)
        set_obs_store(custom)
        assert get_obs_store() is custom
        fresh = reset_obs_store()
        assert isinstance(fresh, InMemoryObservabilityStore)
        assert get_obs_store() is fresh

    def test_record_obs_event(self) -> None:
        reset_obs_store()
        row = record_obs_event(
            "hitl",
            action="queued",
            severity="medium",
        )
        assert row["action"] == "queued"
        assert "id" in row and "ts" in row
        rows, total = get_obs_store().list("hitl", limit=5)
        assert total == 1
        assert rows[0]["action"] == "queued"


class TestCreateObsStoreExtra:
    def test_unknown_backend_defaults_memory(self) -> None:
        with patch.dict(os.environ, {"OBS_STORAGE_BACKEND": "not-a-backend"}):
            store = create_obs_store()
            assert isinstance(store, InMemoryObservabilityStore)

    def test_redis_init_failure_falls_back(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OBS_STORAGE_BACKEND": "redis",
                "OBS_REDIS_URL": "redis://localhost:6379/0",
            },
        ):
            with patch(
                "backend.observability.storage_provider.redis_lib"
            ) as redis_mod:
                redis_mod.Redis.from_url.side_effect = RuntimeError("down")
                store = create_obs_store()
                assert isinstance(store, InMemoryObservabilityStore)


class TestRecordObsEventExtra:
    def test_record_multiple_streams(self) -> None:
        reset_obs_store()
        record_obs_event("security", threat_type="scan")
        record_obs_event("hitl", action="queued")
        record_obs_event("rag", event="refused")
        store = get_obs_store()
        assert store.stats("security")["count"] == 1
        assert store.stats("hitl")["count"] == 1
        assert store.stats("rag")["count"] == 1

    def test_record_overwrites_only_missing_id(self) -> None:
        reset_obs_store()
        row = record_obs_event("s", id="custom-id", severity="high")
        assert row["id"] == "custom-id"
        assert row["severity"] == "high"

    def test_set_custom_store_used_by_record(self) -> None:
        custom = InMemoryObservabilityStore(max_events=10)
        set_obs_store(custom)
        record_obs_event("only-here", v=1)
        rows, total = custom.list("only-here")
        assert total == 1
        assert rows[0]["v"] == 1
        reset_obs_store()


# ---------------------------------------------------------------------------
# Isolation between streams
# ---------------------------------------------------------------------------


class TestStreamIsolation:
    def test_streams_do_not_mix(self) -> None:
        store = InMemoryObservabilityStore()
        store.append("security", {"kind": "sec"})
        store.append("hitl", {"kind": "hitl"})
        sec, st = store.list("security")
        hitl, ht = store.list("hitl")
        assert st == 1 and ht == 1
        assert sec[0]["kind"] == "sec"
        assert hitl[0]["kind"] == "hitl"
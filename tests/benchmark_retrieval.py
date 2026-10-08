import asyncio
import json
import statistics
import time

import httpx

BASE_URL = "http://localhost:8000/retrieval"

# Target dataset of queries for benchmarking
BENCHMARK_QUERIES = [
    "How do phishing detectors handle spoofed email headers?",
    "What are the indicators of a Business Email Compromise (BEC) attack?",
    "How does SPF, DKIM, and DMARC verification work in email security?",
    "What techniques are used in spear phishing and whaling campaigns?",
    "How do machine learning models detect anomalous URL redirects?",
    "What is homograph attack detection in domain name evaluation?",
    "How to analyze email attachments in a secure sandbox environment?",
    "What are zero-day phishing attack vectors in modern threat landscapes?",
]


class BenchmarkRunner:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout

    @staticmethod
    def _calculate_stats(latencies_ms: list[float]) -> dict[str, float]:
        """Calculate statistical metrics for a series of latency measurements."""
        if not latencies_ms:
            return {"count": 0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
        
        sorted_lat = sorted(latencies_ms)
        n = len(sorted_lat)
        
        return {
            "count": n,
            "mean": round(statistics.mean(sorted_lat), 2),
            "p50": round(statistics.median(sorted_lat), 2),
            "p90": round(sorted_lat[int(n * 0.90) - 1 if n >= 10 else -1], 2),
            "p95": round(sorted_lat[int(n * 0.95) - 1 if n >= 10 else -1], 2),
            "max": round(max(sorted_lat), 2),
        }

    async def run_single_search(self, client: httpx.AsyncClient, query: str) -> float:
        """Executes a single search request and returns latency in ms."""
        start = time.perf_counter()
        response = await client.post(
            f"{self.base_url}/search",
            json={
                "query": query,
                "top_k": 5,
                "score_threshold": 0.2,
                "hybrid": True,
            },
        )
        elapsed = (time.perf_counter() - start) * 1000
        assert response.status_code == 200, f"Search failed [{response.status_code}]: {response.text}"
        return elapsed

    async def run_single_stream(self, client: httpx.AsyncClient, query: str) -> dict[str, float]:
        """Measures streaming TTFT (Time to First Token) and total duration."""
        payload = {
            "query": query,
            "top_k": 3,
            "score_threshold": 0.2,
            "hybrid": True,
            "model": "gpt-4o-mini",
        }

        start = time.perf_counter()
        ttft: float | None = None
        tokens_received = 0

        async with client.stream("POST", f"{self.base_url}/generate/stream", json=payload) as response:
            assert response.status_code == 200, f"Stream failed [{response.status_code}]"

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                raw_data = line.replace("data: ", "").strip()
                if not raw_data:
                    continue

                event = json.loads(raw_data)
                event_type = event.get("type")

                if event_type == "token":
                    if ttft is None:
                        ttft = (time.perf_counter() - start) * 1000
                    tokens_received += 1
                elif event_type == "error":
                    raise RuntimeError(f"Streaming server error: {event.get('message')}")

        total_duration = (time.perf_counter() - start) * 1000
        return {
            "ttft_ms": ttft or total_duration,
            "total_ms": total_duration,
            "tokens": tokens_received,
        }

    async def benchmark_concurrent_searches(self, concurrency: int = 10, total_requests: int = 30):
        """Simulates concurrent users hitting the /search endpoint."""
        print(f"\n[Load Test] Executing {total_requests} search requests across {concurrency} parallel workers...")
        latencies = []
        failures = 0

        semaphore = asyncio.Semaphore(concurrency)

        async def worker(query: str):
            nonlocal failures
            async with semaphore:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    try:
                        lat = await self.run_single_search(client, query)
                        latencies.append(lat)
                    except Exception as exc:
                        failures += 1
                        print(f"  ❌ Request failed: {exc}")

        queries_to_run = [BENCHMARK_QUERIES[i % len(BENCHMARK_QUERIES)] for i in range(total_requests)]
        
        start_time = time.perf_counter()
        await asyncio.gather(*[worker(q) for q in queries_to_run])
        total_time_sec = time.perf_counter() - start_time

        stats = self._calculate_stats(latencies)
        rps = round(len(latencies) / total_time_sec, 2)

        print(f"  -> Total Executed: {total_requests} | Success: {len(latencies)} | Failed: {failures}")
        print(f"  -> Throughput: {rps} Requests/Sec")
        print(f"  -> Latency Stats (ms) | Mean: {stats['mean']} | p50: {stats['p50']} | p95: {stats['p95']} | Max: {stats['max']}")
        return stats

    async def benchmark_streaming(self, num_samples: int = 5):
        """Measures streaming TTFT and completion duration across multiple runs."""
        print(f"\n[Stream Test] Running {num_samples} SSE streaming benchmark runs...")
        ttft_list = []
        total_durations = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(num_samples):
                query = BENCHMARK_QUERIES[i % len(BENCHMARK_QUERIES)]
                try:
                    res = await self.run_single_stream(client, query)
                    ttft_list.append(res["ttft_ms"])
                    total_durations.append(res["total_ms"])
                    print(f"  ✓ Sample {i+1}/{num_samples} | TTFT: {res['ttft_ms']:.2f} ms | Total: {res['total_ms']:.2f} ms | Tokens: {res['tokens']}")
                except Exception as exc:
                    print(f"  ❌ Streaming sample {i+1} failed: {exc}")

        ttft_stats = self._calculate_stats(ttft_list)
        total_stats = self._calculate_stats(total_durations)

        print(f"  -> Time To First Token (TTFT) | Median: {ttft_stats['p50']} ms | p95: {ttft_stats['p95']} ms")
        print(f"  -> Total Stream Duration     | Median: {total_stats['p50']} ms | p95: {total_stats['p95']} ms")


async def main():
    print("=" * 70)
    print(" RAG & Retrieval API Full Benchmark Suite")
    print("=" * 70)

    runner = BenchmarkRunner()

    # 1. Standard Concurrency Search Benchmark
    await runner.benchmark_concurrent_searches(concurrency=5, total_requests=20)

    # 2. SSE Streaming Response Benchmark
    await runner.benchmark_streaming(num_samples=5)

    print("\n" + "=" * 70)
    print(" BENCHMARK COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
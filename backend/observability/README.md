# Observability for doc-intelligence RAG

Metrics, cost tracking, and tracing for the RAG pipeline. Metrics are emitted
in `backend/services/rag_service.py` (see `run_rag()` and `synthesize()`).

## Quick start

1. **Install the dependency**
   ```bash
   pip install prometheus-client
   ```

2. **Expose `/metrics` in `backend/main.py`**
   ```python
   from fastapi.responses import Response
   from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

   @app.get("/metrics")
   async def metrics() -&gt; Response:
       return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
   ```

3. **Enable tracing** (optional, free tier works)
   ```bash
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=ls__...
   LANGSMITH_PROJECT=doc-intelligence-prod
   ```

## Metrics emitted

| metric | type | meaning |
|---|---|---|
| `rag_e2e_latency_seconds` | histogram | End-to-end query latency |
| `rag_stage_latency_seconds{stage}` | histogram | Per-stage latency: `embed` / `search` / `synthesize` |
| `rag_tokens_total{model,direction}` | counter | Tokens: `prompt` / `completion` / `embedding` |
| `rag_cost_dollars_total{model}` | counter | Estimated spend (USD) |
| `rag_confidence_score` | histogram | Confidence returned to clients |
| `rag_retrieved_chunks` | histogram | Chunks retrieved per query |
| `rag_synthesis_path_total{path}` | counter | `openai` / `llm_factory` / `extractive_fallback` |

&gt; **Alert on this:** a rising `extractive_fallback` rate means the LLM path is
&gt; failing silently and answer quality has degraded.

## Grafana queries

```
# p95 end-to-end latency
histogram_quantile(0.95, rate(rag_e2e_latency_seconds_bucket[5m]))

# p50 / p95 per stage
histogram_quantile(0.50, sum by (stage, le) (rate(rag_stage_latency_seconds_bucket[5m])))
histogram_quantile(0.95, sum by (stage, le) (rate(rag_stage_latency_seconds_bucket[5m])))

# Spend per hour
rate(rag_cost_dollars_total[1h]) * 3600

# Cost per request
rate(rag_cost_dollars_total[5m]) / rate(rag_e2e_latency_seconds_count[5m])

# Fallback rate (quality regression alarm)
rate(rag_synthesis_path_total{path="extractive_fallback"}[15m])
```

## Local Prometheus + Grafana

Add to `docker-compose.override.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml
    ports: ["9090:9090"]
  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
```

`observability/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: rag-api
    scrape_interval: 15s
    static_configs:
      - targets: ["backend:8000"]
   ```

## Maintenance

- **Pricing:** `cost.py` contains hardcoded USD-per-1M-token prices. Update it
  when OpenAI changes pricing — stale prices silently corrupt cost dashboards
  and CI cost gates.
- **Traces:** view at https://smith.langchain.com (project
  `doc-intelligence-prod`). Every request shows embed → search → synthesize
  spans with token counts and latency waterfall.
- **CI gates:** regression gating lives in `backend/evaluation/gates.py`,
  wired via `.github/workflows/eval-gate.yml`.
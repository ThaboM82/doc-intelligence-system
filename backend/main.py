"""
backend/main.py

Enterprise Document Intelligence & Security API
Render (API) + Vercel (frontend). Qdrant via QDRANT_URL / QDRANT_API_KEY.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_file_path = Path(__file__).resolve()
_backend_dir = _file_path.parent
_workspace_root = _backend_dir.parent
_cwd = Path.cwd()
for _p in (_workspace_root, _backend_dir, _cwd):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

# Optional LangChain OpenAI
try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover
    ChatOpenAI = None  # type: ignore[misc, assignment]

from backend.db.qdrant import (
    close_qdrant_client,
    health_check as qdrant_health_check,
    init_qdrant_collection,
    is_collection_ready,
)
from backend.models.llm_factory import build_default_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("document_intelligence_api")

# ---------------------------------------------------------------------------
# set_active_llm_factory (optional)
# ---------------------------------------------------------------------------
try:
    from backend.routers.intelligence import set_active_llm_factory
except ImportError:  # pragma: no cover

    def set_active_llm_factory(_factory: Any) -> None:
        logger.warning("set_active_llm_factory unavailable")


# ---------------------------------------------------------------------------
# Config & state
# ---------------------------------------------------------------------------
API_VERSION = "1.3.1"
system_start_time = time.time()

request_metrics: dict[str, Any] = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "total_processing_time_ms": 0.0,
    "endpoint_hits": defaultdict(int),
    "status_code_counts": defaultdict(int),
}

rate_limit_tracker: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_TRACKED_CLIENTS = int(os.getenv("RATE_LIMIT_MAX_TRACKED_CLIENTS", "5000"))

API_KEY_HEADER = "X-API-Key"
EXPECTED_ADMIN_KEY = os.getenv("ADMIN_API_KEY", "")

_DEFAULT_CORS = (
    "http://localhost:5173,"
    "http://localhost:3000,"
    "http://127.0.0.1:5173"
)
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS).split(",")
    if o.strip()
]
_ALLOW_ALL_ORIGINS = "*" in CORS_ORIGINS


async def verify_admin_access(
    x_api_key: str | None = Header(None, alias=API_KEY_HEADER),
):
    if EXPECTED_ADMIN_KEY and x_api_key != EXPECTED_ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing administrative API key header.",
        )


def _normalize_metric_path(path: str) -> str:
    normalized = re.sub(r"/[a-f0-9\-]{32,36}", "/{id}", path)
    normalized = re.sub(r"/\d+", "/{id}", normalized)
    return normalized


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Initializing Document Intelligence & Security API services...")

    qdrant_ok = await init_qdrant_collection(raise_on_error=False)
    if qdrant_ok:
        logger.info("Qdrant collection ready")
    else:
        logger.error(
            "Qdrant unavailable at startup — vector features degraded. "
            "Set QDRANT_URL (and QDRANT_API_KEY for Cloud)."
        )

    openai_key = os.getenv("OPENAI_API_KEY", "")
    llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    if ChatOpenAI is not None and openai_key:
        try:
            primary_llm = ChatOpenAI(
                model=os.getenv("LLM_PRIMARY_MODEL", "gpt-4o"),
                temperature=llm_temperature,
            )
            fallback_llm = ChatOpenAI(
                model=os.getenv("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
                temperature=llm_temperature,
            )
            factory = build_default_factory(
                primary=primary_llm,
                fallback=fallback_llm,
                max_retries=2,
                enable_cache=True,
                cache_ttl_sec=300.0,
            )
            set_active_llm_factory(factory)
            logger.info("LLM Factory initialized (primary + fallback)")
        except Exception as exc:
            logger.error("LLM Factory init failed (API will start degraded): %s", exc)
    else:
        logger.warning(
            "Skipping LLM Factory — ChatOpenAI unavailable or OPENAI_API_KEY not set"
        )

    yield

    await close_qdrant_client()
    logger.info("Shut down API services and released system resources.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Document Intelligence & Security API",
    description=(
        "Production REST API for document ingestion, Qdrant vector retrieval, "
        "security validation, prompt injection scanning, RAG search, and "
        "document quarantine management."
    ),
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _ALLOW_ALL_ORIGINS else CORS_ORIGINS,
    allow_credentials=not _ALLOW_ALL_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-MS"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def security_and_telemetry_middleware(request: Request, call_next):
    start_time = time.time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "127.0.0.1")
    )

    now = time.time()
    hits = [
        t
        for t in rate_limit_tracker[client_ip]
        if now - t < RATE_LIMIT_WINDOW_SECONDS
    ]
    rate_limit_tracker[client_ip] = hits

    if len(rate_limit_tracker) > RATE_LIMIT_MAX_TRACKED_CLIENTS:
        for ip in [ip for ip, ts in rate_limit_tracker.items() if not ts]:
            rate_limit_tracker.pop(ip, None)

    if len(hits) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "Rate Limit Exceeded",
                "detail": (
                    f"Maximum limit of {RATE_LIMIT_MAX_REQUESTS} "
                    f"requests per {RATE_LIMIT_WINDOW_SECONDS}s reached."
                ),
                "request_id": request_id,
            },
        )
    rate_limit_tracker[client_ip].append(now)

    try:
        response: Response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        normalized_path = _normalize_metric_path(request.url.path)
        request_metrics["total_requests"] += 1
        request_metrics["status_code_counts"][response.status_code] += 1
        if response.status_code < 400:
            request_metrics["successful_requests"] += 1
        else:
            request_metrics["failed_requests"] += 1
        request_metrics["total_processing_time_ms"] += duration_ms
        request_metrics["endpoint_hits"][normalized_path] += 1

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-MS"] = str(duration_ms)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
    except Exception as exc:
        request_metrics["total_requests"] += 1
        request_metrics["failed_requests"] += 1
        request_metrics["status_code_counts"][500] += 1
        logger.error(
            "Unhandled exception on path %s [ID: %s]: %s",
            request.url.path,
            request_id,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "detail": "An unhandled error occurred while processing your request.",
                "request_id": request_id,
            },
        )


# ---------------------------------------------------------------------------
# Optional routers (import once; log full failures)
# ---------------------------------------------------------------------------
HeaderValidator = None
PromptInjectionDetector = None
intelligence_router = None
ingestion_router = None
security_router = None
rag_router = None
pipeline = None


def _load_security_validators():
    for module_name in ("backend.security.validators", "app.security.validators"):
        try:
            module = importlib.import_module(module_name)
            header_validator = getattr(module, "HeaderValidator", None)
            prompt_detector = getattr(module, "PromptInjectionDetector", None)
            if header_validator is not None or prompt_detector is not None:
                return header_validator, prompt_detector
        except Exception:
            continue
    logger.warning("Security validators could not be imported.")
    return None, None


HeaderValidator, PromptInjectionDetector = _load_security_validators()

try:
    from backend.routers.intelligence import router as intelligence_router
except ImportError:
    logger.exception("Intelligence router could not be imported.")

for _module_name in (
    "backend.routers.ingestion",
    "backend.api.routes.ingestion",
    "app.routers.ingestion",
):
    try:
        ingestion_router = getattr(importlib.import_module(_module_name), "router", None)
        if ingestion_router is not None:
            break
    except ImportError:
        continue
if ingestion_router is None:
    logger.warning("Ingestion module could not be imported.")

for _module_name in (
    "backend.routers.security",
    "backend.api.routes.security",
    "app.routers.security",
):
    try:
        security_router = getattr(importlib.import_module(_module_name), "router", None)
        if security_router is not None:
            break
    except ImportError:
        continue
if security_router is None:
    logger.warning("Security router could not be imported.")

try:
    from backend.routers.rag import router as rag_router
except Exception:
    logger.exception("RAG router could not be imported.")

# Mount once. Routers that already define prefix="/api/v1/..." get NO extra prefix.
if intelligence_router is not None:
    app.include_router(intelligence_router)
    logger.info("Registered intelligence router")

if ingestion_router is not None:
    app.include_router(ingestion_router)
    logger.info("Registered ingestion router")

if security_router is not None:
    app.include_router(security_router)
    logger.info("Registered security router")
else:
    logger.warning("Security router missing — built-in fallback routes will apply.")

if rag_router is not None:
    app.include_router(rag_router)
    logger.info("Registered RAG router at /api/v1/rag")
else:
    logger.warning("RAG router missing — stub /api/v1/rag/query fallback will apply.")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SystemStatusResponse(BaseModel):
    status: str = Field(..., json_schema_extra={"example": "ok"})
    uptime_seconds: float = Field(..., json_schema_extra={"example": 3600.5})
    total_requests: int = Field(..., json_schema_extra={"example": 150})
    memory_usage_mb: float | None = Field(None, json_schema_extra={"example": 256.4})
    cpu_percent: float | None = Field(None, json_schema_extra={"example": 12.5})
    qdrant_ok: bool = Field(False, json_schema_extra={"example": True})
    collection_ready: bool = Field(False, json_schema_extra={"example": True})


class ReadinessProbeResponse(BaseModel):
    status: str
    validators_ready: bool
    pipeline_ready: bool
    qdrant_ready: bool
    details: dict[str, Any]


class TelemetryResponse(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_latency_ms: float
    endpoint_distribution: dict[str, int]
    status_code_distribution: dict[int, int]


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(5, ge=1, le=20)
    filter_metadata: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = []
    confidence_score: float = 0.0
    processing_time_ms: float = 0.0


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    security_scan_passed: bool
    message: str


class QuarantineItem(BaseModel):
    document_id: str
    filename: str
    threat_detected: str
    quarantined_at: float


class VerifyHeadersRequest(BaseModel):
    headers: dict[str, Any]


class ScanPromptRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Security response helpers
# ---------------------------------------------------------------------------
def _header_api_response(report: Any) -> dict[str, Any]:
    findings = list(getattr(report, "findings", None) or [])
    threats = [
        f
        for f in findings
        if "passed" not in str(f).lower() and "all authentication" not in str(f).lower()
    ]
    suspicious = bool(getattr(report, "is_suspicious", False))
    return {
        "passed": not suspicious,
        "risk_score": float(getattr(report, "risk_score", 0.0) or 0.0),
        "threats_detected": threats,
        "details": {
            "spf_status": getattr(report, "spf_status", "none"),
            "dkim_status": getattr(report, "dkim_status", "none"),
            "dmarc_status": getattr(report, "dmarc_status", "none"),
            "dmarc_policy": getattr(report, "dmarc_policy", "none"),
            "arc_status": getattr(report, "arc_status", "none"),
            "domain_aligned": getattr(report, "domain_aligned", True),
            "from_domain": getattr(report, "from_domain", ""),
            "return_path_domain": getattr(report, "return_path_domain", ""),
            "findings": findings,
        },
        "spf_status": getattr(report, "spf_status", "none"),
        "dkim_status": getattr(report, "dkim_status", "none"),
        "dmarc_status": getattr(report, "dmarc_status", "none"),
        "domain_aligned": getattr(report, "domain_aligned", True),
        "is_suspicious": suspicious,
    }


def _prompt_api_response(report: Any) -> dict[str, Any]:
    patterns = list(getattr(report, "matched_patterns", None) or [])
    anomalies = list(getattr(report, "detected_anomalies", None) or [])
    threats = patterns if patterns else anomalies
    flagged = bool(getattr(report, "is_flagged", False))
    return {
        "passed": not flagged,
        "risk_score": float(getattr(report, "risk_score", 0.0) or 0.0),
        "threats_detected": threats,
        "details": {
            "severity": getattr(report, "severity", "clean"),
            "matched_patterns": patterns,
            "detected_anomalies": anomalies,
            "threat_categories": list(getattr(report, "threat_categories", None) or []),
            "entropy_score": getattr(report, "entropy_score", 0.0),
        },
        "is_flagged": flagged,
        "severity": getattr(report, "severity", "clean"),
        "matched_patterns": patterns,
        "detected_anomalies": anomalies,
    }


# ---------------------------------------------------------------------------
# Security fallback routes (only if no security_router)
# ---------------------------------------------------------------------------
if security_router is None:

    @app.post("/api/v1/security/verify-headers", tags=["Security"])
    async def verify_headers_fallback(payload: VerifyHeadersRequest):
        if HeaderValidator is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Header validator not available.",
            )
        if not payload.headers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Headers dictionary cannot be empty.",
            )
        try:
            report = HeaderValidator.verify_spf_dkim_dmarc(payload.headers)
            return _header_api_response(report)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse or validate email headers: {exc}",
            ) from exc

    @app.post("/api/v1/security/scan-prompt", tags=["Security"])
    async def scan_prompt_fallback(payload: ScanPromptRequest):
        if PromptInjectionDetector is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Prompt injection detector not available.",
            )
        try:
            report = PromptInjectionDetector.scan_text(payload.text)
            return _prompt_api_response(report)
        except Exception as exc:
            logger.exception("scan-prompt failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error executing security scan: {exc}",
            ) from exc

    @app.post("/api/v1/security/scan-document", tags=["Security"])
    async def scan_document_fallback(
        file: UploadFile = File(...),
        headers_json: str | None = Form(None),
    ):
        if PromptInjectionDetector is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Prompt injection detector not available.",
            )
        headers: dict[str, Any] = {}
        if headers_json is not None and str(headers_json).strip():
            try:
                headers = json.loads(headers_json)
                if not isinstance(headers, dict):
                    raise ValueError("headers_json must be a JSON object")
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid JSON string in headers_json: {exc}",
                ) from exc

        raw = await file.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""

        try:
            injection = PromptInjectionDetector.scan_text(text)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error executing security scan: {exc}",
            ) from exc

        header_report = None
        if headers and HeaderValidator is not None:
            try:
                header_report = HeaderValidator.verify_spf_dkim_dmarc(headers)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to parse or validate email headers: {exc}",
                ) from exc

        inj = _prompt_api_response(injection)
        threats = list(inj.get("threats_detected") or [])
        flagged = not inj.get("passed", True)
        risk = float(inj.get("risk_score") or 0.0)

        if header_report is not None:
            hdr = _header_api_response(header_report)
            if not hdr.get("passed", True):
                flagged = True
            risk = max(risk, float(hdr.get("risk_score") or 0.0))
            threats = threats + list(hdr.get("threats_detected") or [])

        return {
            "filename": file.filename or "upload",
            "is_flagged": flagged,
            "status": "quarantined" if flagged else "verified_safe",
            "threats_detected": threats,
            "risk_score": risk,
            "injection": inj,
            "headers": _header_api_response(header_report) if header_report else None,
        }

    logger.info("Built-in security fallback routes registered at /api/v1/security/*")


# ---------------------------------------------------------------------------
# Core probes
# ---------------------------------------------------------------------------
@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    return {
        "system": "Document Intelligence & Security API",
        "version": API_VERSION,
        "status": "operational",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "ready": "/ready",
        "metrics": "/metrics",
        "rag": "/api/v1/rag/query",
        "security": "/api/v1/security",
    }


@app.get("/health", response_model=SystemStatusResponse, status_code=status.HTTP_200_OK)
async def health_check():
    uptime = round(time.time() - system_start_time, 2)
    memory_mb = None
    cpu_usage = None
    if psutil:
        try:
            process = psutil.Process()
            memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
            cpu_usage = psutil.cpu_percent(interval=None)
        except Exception as exc:  # pragma: no cover
            logger.warning("psutil stats failed: %s", exc)

    qdrant = await qdrant_health_check()
    qdrant_ok = bool(qdrant.get("ok"))
    coll_ready = is_collection_ready()

    return SystemStatusResponse(
        status="ok" if qdrant_ok and coll_ready else "degraded",
        uptime_seconds=uptime,
        total_requests=request_metrics["total_requests"],
        memory_usage_mb=memory_mb,
        cpu_percent=cpu_usage,
        qdrant_ok=qdrant_ok,
        collection_ready=coll_ready,
    )


@app.get("/ready", response_model=ReadinessProbeResponse, status_code=status.HTTP_200_OK)
async def readiness_check():
    validators_ok = bool(PromptInjectionDetector and HeaderValidator)
    pipeline_ok = pipeline is not None
    qdrant = await qdrant_health_check()
    qdrant_ok = bool(qdrant.get("ok")) and is_collection_ready()

    status_str = (
        "ready" if (validators_ok and pipeline_ok and qdrant_ok) else "degraded"
    )
    return ReadinessProbeResponse(
        status=status_str,
        validators_ready=validators_ok,
        pipeline_ready=pipeline_ok,
        qdrant_ready=qdrant_ok,
        details={
            "prompt_injection_detector": (
                "active" if PromptInjectionDetector else "unavailable"
            ),
            "header_validator": "active" if HeaderValidator else "unavailable",
            "ingestion_pipeline": "active" if pipeline_ok else "unavailable",
            "security_router": "mounted" if security_router is not None else "fallback",
            "rag_router": "mounted" if rag_router is not None else "fallback",
            "qdrant": qdrant,
        },
    )


@app.get("/telemetry", response_model=TelemetryResponse, status_code=status.HTTP_200_OK)
async def get_telemetry(_: None = Depends(verify_admin_access)):
    avg_latency = 0.0
    if request_metrics["total_requests"] > 0:
        avg_latency = round(
            request_metrics["total_processing_time_ms"]
            / request_metrics["total_requests"],
            2,
        )
    return TelemetryResponse(
        total_requests=request_metrics["total_requests"],
        successful_requests=request_metrics["successful_requests"],
        failed_requests=request_metrics["failed_requests"],
        average_latency_ms=avg_latency,
        endpoint_distribution=dict(request_metrics["endpoint_hits"]),
        status_code_distribution=dict(request_metrics["status_code_counts"]),
    )


@app.get("/metrics", response_class=PlainTextResponse, status_code=status.HTTP_200_OK)
async def prometheus_metrics():
    uptime = round(time.time() - system_start_time, 2)
    avg_latency = 0.0
    if request_metrics["total_requests"] > 0:
        avg_latency = round(
            request_metrics["total_processing_time_ms"]
            / request_metrics["total_requests"],
            2,
        )
    qdrant_ready_gauge = 1 if is_collection_ready() else 0
    lines = [
        "# HELP doc_intelligence_uptime_seconds Total runtime in seconds",
        "# TYPE doc_intelligence_uptime_seconds counter",
        f"doc_intelligence_uptime_seconds {uptime}",
        "# HELP doc_intelligence_requests_total Total HTTP requests processed",
        "# TYPE doc_intelligence_requests_total counter",
        f"doc_intelligence_requests_total {request_metrics['total_requests']}",
        "# HELP doc_intelligence_requests_successful Total successful requests",
        "# TYPE doc_intelligence_requests_successful counter",
        f"doc_intelligence_requests_successful {request_metrics['successful_requests']}",
        "# HELP doc_intelligence_requests_failed Total failed requests",
        "# TYPE doc_intelligence_requests_failed counter",
        f"doc_intelligence_requests_failed {request_metrics['failed_requests']}",
        "# HELP doc_intelligence_average_latency_ms Average request latency in ms",
        "# TYPE doc_intelligence_average_latency_ms gauge",
        f"doc_intelligence_average_latency_ms {avg_latency}",
        "# HELP doc_intelligence_qdrant_ready Qdrant collection ready (1/0)",
        "# TYPE doc_intelligence_qdrant_ready gauge",
        f"doc_intelligence_qdrant_ready {qdrant_ready_gauge}",
    ]
    for path, count in request_metrics["endpoint_hits"].items():
        lines.append(f'doc_intelligence_endpoint_hits_total{{path="{path}"}} {count}')
    for code, count in request_metrics["status_code_counts"].items():
        lines.append(f'doc_intelligence_status_code_total{{code="{code}"}} {count}')
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# RAG fallback (only if rag_router failed to load)
# ---------------------------------------------------------------------------
if rag_router is None:

    @app.post(
        "/api/v1/rag/query",
        response_model=QueryResponse,
        tags=["RAG Search & Intelligence"],
    )
    async def execute_rag_query_fallback(payload: QueryRequest):
        start = time.time()
        duration = round((time.time() - start) * 1000, 2)
        return QueryResponse(
            answer=(
                f"RAG module not loaded. Stub response for: '{payload.query}'. "
                "Fix backend.routers.rag import and restart."
            ),
            sources=[],
            confidence_score=0.0,
            processing_time_ms=duration,
        )


# ---------------------------------------------------------------------------
# Document routes (stubs until ingestion pipeline is wired)
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/documents/upload",
    response_model=DocumentUploadResponse,
    tags=["Document Management"],
)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
):
    doc_id = str(uuid.uuid4())
    filename = file.filename or "upload.bin"
    # Drain body so client connections close cleanly
    await file.read()
    return DocumentUploadResponse(
        document_id=doc_id,
        filename=filename,
        status="queued_for_ingestion",
        security_scan_passed=True,
        message=(
            "Document accepted. Full Docling/Qdrant ingestion pipeline not wired yet; "
            "use seed_qdrant.py for corpus bootstrap."
        ),
    )


@app.delete(
    "/api/v1/documents/{document_id}",
    status_code=status.HTTP_200_OK,
    tags=["Document Management"],
)
async def delete_document(document_id: str):
    return {
        "status": "success",
        "message": f"Document {document_id} delete requested (stub).",
    }


@app.get(
    "/api/v1/documents/quarantine",
    response_model=list[QuarantineItem],
    tags=["Document Management"],
)
async def list_quarantined_documents(_: None = Depends(verify_admin_access)):
    return [
        QuarantineItem(
            document_id="q-doc-999",
            filename="suspicious_payload.pdf",
            threat_detected="Indirect Prompt Injection / Malicious Instructions",
            quarantined_at=time.time() - 3600,
        )
    ]


# ---------------------------------------------------------------------------
# OpenAPI + exception handlers
# ---------------------------------------------------------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Document Intelligence & Security API",
        version=API_VERSION,
        description=(
            "Enterprise REST API for Document Parsing, RAG Vector Search, "
            "Header Authentication, and Indirect Prompt Injection Safeguards."
        ),
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "message": "Input validation failed for request parameters.",
            "details": exc.errors(),
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            "detail": exc.detail,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
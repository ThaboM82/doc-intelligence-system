"""
Cost-per-request tracking.

Pricing: USD per 1M tokens. UPDATE THIS TABLE when model pricing changes —
stale pricing silently corrupts cost dashboards and CI cost gates.
Source: https://openai.com/api/pricing/ (verify periodically).

Env (optional):
  COST_TRACKING_ENABLED=true|false   (default true)
  COST_DEFAULT_CHAT_MODEL=gpt-4o-mini
  COST_DEFAULT_EMBED_MODEL=text-embedding-3-small
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Pricing tables — USD per 1M tokens
# ---------------------------------------------------------------------------

# model -> ($/1M input tokens, $/1M output tokens)
CHAT_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-3.5-turbo": (0.50, 1.50),
}

# model -> $/1M tokens (embeddings bill input only)
EMBED_PRICING: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}

# Common aliases / dated model ids -> canonical pricing key
_MODEL_ALIASES: dict[str, str] = {
    "gpt-4o-2024-08-06": "gpt-4o",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4.1-2025-04-14": "gpt-4.1",
    "gpt-4.1-mini-2025-04-14": "gpt-4.1-mini",
    "text-embedding-3-small-": "text-embedding-3-small",
}

COST_TRACKING_ENABLED = os.getenv("COST_TRACKING_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEFAULT_CHAT_MODEL = os.getenv("COST_DEFAULT_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_EMBED_MODEL = os.getenv(
    "COST_DEFAULT_EMBED_MODEL", "text-embedding-3-small"
)


def normalize_model(model: str | None) -> str:
    """Map provider model ids to a pricing table key."""
    if not model:
        return ""
    m = model.strip()
    if m in CHAT_PRICING or m in EMBED_PRICING:
        return m
    if m in _MODEL_ALIASES:
        return _MODEL_ALIASES[m]
    # strip date suffix: name-YYYY-MM-DD
    parts = m.rsplit("-", 3)
    if len(parts) >= 4 and all(p.isdigit() for p in parts[-3:]):
        base = "-".join(parts[:-3])
        if base in CHAT_PRICING or base in EMBED_PRICING:
            return base
    return m


def chat_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Cost of one chat completion in USD."""
    key = normalize_model(model)
    inp, out = CHAT_PRICING.get(key, (0.0, 0.0))
    pt = max(0, int(prompt_tokens or 0))
    ct = max(0, int(completion_tokens or 0))
    return (pt * inp + ct * out) / 1_000_000


def embed_cost(model: str, tokens: int) -> float:
    """Cost of one embedding call in USD."""
    key = normalize_model(model)
    rate = EMBED_PRICING.get(key, 0.0)
    t = max(0, int(tokens or 0))
    return t * rate / 1_000_000


def has_chat_pricing(model: str) -> bool:
    return normalize_model(model) in CHAT_PRICING


def has_embed_pricing(model: str) -> bool:
    return normalize_model(model) in EMBED_PRICING


# ---------------------------------------------------------------------------
# Records + in-memory ledger
# ---------------------------------------------------------------------------


@dataclass
class CostEvent:
    kind: str  # "chat" | "embed"
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    request_id: str | None = None
    route: str | None = None
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CostTracker:
    """
    Thread-safe in-process cost accumulator.

    Suitable for single-instance Render services and local dev.
    For multi-instance, export events to your metrics backend.
    """

    def __init__(self, max_events: int = 2000) -> None:
        self._lock = threading.Lock()
        self._max_events = max(100, int(max_events))
        self._events: list[CostEvent] = []
        self.total_cost_usd: float = 0.0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_embed_tokens: int = 0
        self.by_model: dict[str, float] = defaultdict(float)
        self.by_kind: dict[str, float] = defaultdict(float)
        self.by_route: dict[str, float] = defaultdict(float)
        self.call_counts: dict[str, int] = defaultdict(int)

    def record_chat(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        request_id: str | None = None,
        route: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> CostEvent:
        model_n = normalize_model(model) or DEFAULT_CHAT_MODEL
        cost = chat_cost(model_n, prompt_tokens, completion_tokens)
        total = int(prompt_tokens or 0) + int(completion_tokens or 0)
        ev = CostEvent(
            kind="chat",
            model=model_n,
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            total_tokens=total,
            cost_usd=round(cost, 8),
            request_id=request_id,
            route=route,
            meta=dict(meta or {}),
        )
        if COST_TRACKING_ENABLED:
            self._commit(ev)
        return ev

    def record_embed(
        self,
        model: str,
        tokens: int,
        *,
        request_id: str | None = None,
        route: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> CostEvent:
        model_n = normalize_model(model) or DEFAULT_EMBED_MODEL
        cost = embed_cost(model_n, tokens)
        ev = CostEvent(
            kind="embed",
            model=model_n,
            prompt_tokens=int(tokens or 0),
            completion_tokens=0,
            total_tokens=int(tokens or 0),
            cost_usd=round(cost, 8),
            request_id=request_id,
            route=route,
            meta=dict(meta or {}),
        )
        if COST_TRACKING_ENABLED:
            self._commit(ev)
        return ev

    def _commit(self, ev: CostEvent) -> None:
        with self._lock:
            self._events.append(ev)
            if len(self._events) > self._max_events:
                overflow = len(self._events) - self._max_events
                del self._events[:overflow]
            self.total_cost_usd = round(self.total_cost_usd + ev.cost_usd, 8)
            if ev.kind == "chat":
                self.total_prompt_tokens += ev.prompt_tokens
                self.total_completion_tokens += ev.completion_tokens
            else:
                self.total_embed_tokens += ev.total_tokens
            self.by_model[ev.model] = round(
                self.by_model[ev.model] + ev.cost_usd, 8
            )
            self.by_kind[ev.kind] = round(
                self.by_kind[ev.kind] + ev.cost_usd, 8
            )
            if ev.route:
                self.by_route[ev.route] = round(
                    self.by_route[ev.route] + ev.cost_usd, 8
                )
            self.call_counts[ev.kind] += 1
            self.call_counts[f"model:{ev.model}"] += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": COST_TRACKING_ENABLED,
                "total_cost_usd": round(self.total_cost_usd, 6),
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_embed_tokens": self.total_embed_tokens,
                "by_model_usd": dict(self.by_model),
                "by_kind_usd": dict(self.by_kind),
                "by_route_usd": dict(self.by_route),
                "call_counts": dict(self.call_counts),
                "events_retained": len(self._events),
            }

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events[-max(1, n) :]]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self.total_cost_usd = 0.0
            self.total_prompt_tokens = 0
            self.total_completion_tokens = 0
            self.total_embed_tokens = 0
            self.by_model.clear()
            self.by_kind.clear()
            self.by_route.clear()
            self.call_counts.clear()


# Process-wide singleton
_tracker = CostTracker()


def get_cost_tracker() -> CostTracker:
    return _tracker


def estimate_rag_cost(
    *,
    embed_model: str = DEFAULT_EMBED_MODEL,
    chat_model: str = DEFAULT_CHAT_MODEL,
    query_tokens: int = 200,
    context_tokens: int = 2000,
    completion_tokens: int = 400,
    embed_doc_tokens: int = 0,
) -> dict[str, float]:
    """
    Rough cost estimate for one RAG turn (+ optional doc embed).
    Useful for UI hints and CI budgets.
    """
    e = embed_cost(embed_model, query_tokens + max(0, embed_doc_tokens))
    c = chat_cost(chat_model, query_tokens + context_tokens, completion_tokens)
    return {
        "embed_usd": round(e, 8),
        "chat_usd": round(c, 8),
        "total_usd": round(e + c, 8),
    }


def assert_cost_under(
    max_usd: float,
    *,
    tracker: CostTracker | None = None,
) -> None:
    """
    CI / eval gate: raise if cumulative tracked cost exceeds budget.
    """
    t = tracker or _tracker
    total = t.summary()["total_cost_usd"]
    if total > max_usd:
        raise AssertionError(
            f"Cost gate failed: ${total:.6f} exceeds budget ${max_usd:.6f}"
        )


__all__ = [
    "CHAT_PRICING",
    "EMBED_PRICING",
    "normalize_model",
    "chat_cost",
    "embed_cost",
    "has_chat_pricing",
    "has_embed_pricing",
    "CostEvent",
    "CostTracker",
    "get_cost_tracker",
    "estimate_rag_cost",
    "assert_cost_under",
]
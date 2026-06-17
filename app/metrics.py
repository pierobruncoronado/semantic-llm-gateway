"""In-memory aggregate counters for GET /metrics.

Single-worker assumption: module-level globals updated without a lock, same
assumption already documented in app/cache.py (Dia 3 - single uvicorn worker,
no real concurrency on the increments). Scaling to multiple workers/processes
would require a shared store (e.g. the same Upstash Vector/Redis already in
the stack) instead of process-local counters - not done here, see
docs/DECISIONS.md "Dia 5".
"""

_cache_hits = 0
_cache_misses = 0
_injection_blocked = 0
_hit_latency_sum_ms = 0.0
_miss_latency_sum_ms = 0.0
_tokens_saved_input = 0
_tokens_saved_output = 0


def record_hit(latency_ms: float, input_tokens: int, output_tokens: int) -> None:
    global _cache_hits, _hit_latency_sum_ms, _tokens_saved_input, _tokens_saved_output
    _cache_hits += 1
    _hit_latency_sum_ms += latency_ms
    _tokens_saved_input += input_tokens
    _tokens_saved_output += output_tokens


def record_miss(latency_ms: float) -> None:
    global _cache_misses, _miss_latency_sum_ms
    _cache_misses += 1
    _miss_latency_sum_ms += latency_ms


def record_blocked() -> None:
    global _injection_blocked
    _injection_blocked += 1


def snapshot() -> dict:
    total_attempts = _cache_hits + _cache_misses
    return {
        "cache_hits": _cache_hits,
        "cache_misses": _cache_misses,
        "hit_rate": (_cache_hits / total_attempts) if total_attempts else None,
        "avg_latency_hit_ms": (
            round(_hit_latency_sum_ms / _cache_hits, 1) if _cache_hits else None
        ),
        "avg_latency_miss_ms": (
            round(_miss_latency_sum_ms / _cache_misses, 1) if _cache_misses else None
        ),
        "tokens_saved": {
            "input_tokens": _tokens_saved_input,
            "output_tokens": _tokens_saved_output,
        },
        "injection_blocked_count": _injection_blocked,
    }

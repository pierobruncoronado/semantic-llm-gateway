import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import abuse, cache, metrics
from app.config import (
    ANTHROPIC_API_KEY,
    DEFAULT_MODEL,
    MAX_MESSAGE_CHARS,
    MAX_PAYLOAD_BYTES,
)
from app.embeddings import EmbeddingError, embed
from app.injection import check_injection
from app.log import log_event
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import CompletionRequest, Message, ProviderError

app = FastAPI(title="semantic-llm-gateway")
provider = AnthropicProvider(api_key=ANTHROPIC_API_KEY)


@app.middleware("http")
async def payload_cap_middleware(request: Request, call_next):
    if request.url.path == "/v1/messages":
        body = await request.body()
        if len(body) > MAX_PAYLOAD_BYTES:
            log_event(event="payload_rejected", payload_bytes=len(body))
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload too large."},
            )
    return await call_next(request)


class MessageIn(BaseModel):
    role: str
    content: Any


class CompletionRequestIn(BaseModel):
    model: str = DEFAULT_MODEL
    messages: list[MessageIn]
    max_tokens: int
    system: str | None = None


def _cache_key_text(messages: list[MessageIn]) -> str | None:
    for m in reversed(messages):
        if m.role == "user" and isinstance(m.content, str):
            return m.content
    return None


@app.get("/metrics")
async def get_metrics():
    return metrics.snapshot()


@app.post("/v1/messages")
async def create_message(body: CompletionRequestIn, http_request: Request):
    bucket_key = http_request.headers.get("x-api-key") or (
        http_request.client.host if http_request.client else "unknown"
    )
    if abuse.is_rate_limited(bucket_key):
        log_event(event="rate_limited", bucket=abuse.mask_key(bucket_key))
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
        )

    for m in body.messages:
        if isinstance(m.content, str) and len(m.content) > MAX_MESSAGE_CHARS:
            log_event(
                event="input_truncated",
                original_length=len(m.content),
                truncated_length=MAX_MESSAGE_CHARS,
            )
            m.content = m.content[:MAX_MESSAGE_CHARS]

    request = CompletionRequest(
        model=body.model,
        messages=[Message(role=m.role, content=m.content) for m in body.messages],
        max_tokens=body.max_tokens,
        system=body.system,
    )

    cache_text = _cache_key_text(body.messages)

    if cache_text is not None:
        match = check_injection(cache_text)
        if match is not None:
            metrics.record_blocked()
            log_event(
                event="injection_blocked",
                injection_blocked=True,
                pattern_matched=match.pattern_name,
                prompt_length=len(cache_text),
            )
            raise HTTPException(
                status_code=400,
                detail="Request blocked: prompt matched a known injection pattern.",
            )

    vector: list[float] | None = None
    embedding_ms = None
    cache_lookup_ms = None

    if cache_text is not None:
        embed_start = time.monotonic()
        try:
            vector = embed(cache_text)
        except EmbeddingError:
            vector = None
        embedding_ms = round((time.monotonic() - embed_start) * 1000, 1)

        if vector is not None:
            lookup_start = time.monotonic()
            hit = cache.query(vector)
            cache_lookup_ms = round((time.monotonic() - lookup_start) * 1000, 1)

            if hit is not None:
                metrics.record_hit(
                    embedding_ms + cache_lookup_ms,
                    hit.input_tokens,
                    hit.output_tokens,
                )
                log_event(
                    event="request_complete",
                    model=hit.model,
                    input_tokens=hit.input_tokens,
                    output_tokens=hit.output_tokens,
                    cache_hit=True,
                    similarity_score=hit.similarity_score,
                    embedding_ms=embedding_ms,
                    cache_lookup_ms=cache_lookup_ms,
                    injection_blocked=False,
                )
                return {
                    "id": None,
                    "type": "message",
                    "role": "assistant",
                    "model": hit.model,
                    "content": hit.response,
                    "stop_reason": "end_turn",
                    "usage": {
                        "input_tokens": hit.input_tokens,
                        "output_tokens": hit.output_tokens,
                    },
                }

    upstream_start = time.monotonic()
    try:
        response = await provider.complete(request)
    except ProviderError as e:
        log_event(
            event="upstream_error",
            model=body.model,
            status_code=e.status_code,
            latency_ms=round((time.monotonic() - upstream_start) * 1000, 1),
        )
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    upstream_ms = round((time.monotonic() - upstream_start) * 1000, 1)

    if vector is not None:
        cache.store(
            vector=vector,
            response=response.content,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    miss_latency_ms = sum(
        ms for ms in (embedding_ms, cache_lookup_ms, upstream_ms) if ms is not None
    )
    metrics.record_miss(miss_latency_ms)
    log_event(
        event="request_complete",
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_hit=False,
        embedding_ms=embedding_ms,
        cache_lookup_ms=cache_lookup_ms,
        upstream_ms=upstream_ms,
        injection_blocked=False,
    )

    return {
        "id": response.raw.get("id"),
        "type": "message",
        "role": "assistant",
        "model": response.model,
        "content": response.content,
        "stop_reason": response.stop_reason,
        "usage": {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        },
    }

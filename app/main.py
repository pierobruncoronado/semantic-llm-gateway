import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import cache
from app.config import ANTHROPIC_API_KEY, DEFAULT_MODEL
from app.embeddings import EmbeddingError, embed
from app.log import log_event
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import CompletionRequest, Message, ProviderError

app = FastAPI(title="semantic-llm-gateway")
provider = AnthropicProvider(api_key=ANTHROPIC_API_KEY)


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


@app.post("/v1/messages")
async def create_message(body: CompletionRequestIn):
    request = CompletionRequest(
        model=body.model,
        messages=[Message(role=m.role, content=m.content) for m in body.messages],
        max_tokens=body.max_tokens,
        system=body.system,
    )

    cache_text = _cache_key_text(body.messages)
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
                log_event(
                    event="request_complete",
                    model=hit.model,
                    input_tokens=hit.input_tokens,
                    output_tokens=hit.output_tokens,
                    cache_hit=True,
                    similarity_score=hit.similarity_score,
                    embedding_ms=embedding_ms,
                    cache_lookup_ms=cache_lookup_ms,
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

    log_event(
        event="request_complete",
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_hit=False,
        embedding_ms=embedding_ms,
        cache_lookup_ms=cache_lookup_ms,
        upstream_ms=upstream_ms,
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

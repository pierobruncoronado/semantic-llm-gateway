import json
import sys
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import ANTHROPIC_API_KEY, DEFAULT_MODEL
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


def log_event(**fields: Any) -> None:
    print(json.dumps(fields, default=str), file=sys.stdout, flush=True)


@app.post("/v1/messages")
async def create_message(body: CompletionRequestIn):
    request = CompletionRequest(
        model=body.model,
        messages=[Message(role=m.role, content=m.content) for m in body.messages],
        max_tokens=body.max_tokens,
        system=body.system,
    )

    start = time.monotonic()
    try:
        response = await provider.complete(request)
    except ProviderError as e:
        log_event(
            event="upstream_error",
            model=body.model,
            status_code=e.status_code,
            latency_ms=round((time.monotonic() - start) * 1000, 1),
        )
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    latency_ms = round((time.monotonic() - start) * 1000, 1)

    log_event(
        event="request_complete",
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_upstream_ms=latency_ms,
        cache_hit=False,
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

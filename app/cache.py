import time
import uuid
from dataclasses import dataclass
from typing import Any

from upstash_vector import Index

from app.config import (
    CACHE_SIMILARITY_THRESHOLD,
    UPSTASH_VECTOR_REST_TOKEN,
    UPSTASH_VECTOR_REST_URL,
)
from app.log import log_event


@dataclass
class CacheHit:
    response: Any
    model: str
    input_tokens: int
    output_tokens: int
    similarity_score: float


_index = Index(url=UPSTASH_VECTOR_REST_URL, token=UPSTASH_VECTOR_REST_TOKEN)


def query(vector: list[float]) -> CacheHit | None:
    try:
        results = _index.query(vector=vector, top_k=1, include_metadata=True)
    except Exception as e:
        log_event(event="cache_lookup_failed", error=str(e))
        return None

    if not results:
        return None

    top = results[0]
    if top.score < CACHE_SIMILARITY_THRESHOLD:
        return None

    metadata = top.metadata or {}
    return CacheHit(
        response=metadata.get("response"),
        model=metadata.get("model"),
        input_tokens=metadata.get("input_tokens", 0),
        output_tokens=metadata.get("output_tokens", 0),
        similarity_score=top.score,
    )


def store(
    vector: list[float],
    response: Any,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    try:
        _index.upsert(
            vectors=[
                (
                    str(uuid.uuid4()),
                    vector,
                    {
                        "response": response,
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "created_at": time.time(),
                    },
                )
            ]
        )
    except Exception as e:
        log_event(event="cache_store_failed", error=str(e))
        return

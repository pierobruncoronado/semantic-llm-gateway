import voyageai

from app.config import VOYAGE_API_KEY, VOYAGE_MODEL
from app.log import log_event


class EmbeddingError(Exception):
    pass


_client = voyageai.Client(api_key=VOYAGE_API_KEY)


def embed(text: str) -> list[float]:
    try:
        result = _client.embed(texts=[text], model=VOYAGE_MODEL)
    except Exception as e:
        log_event(event="embedding_failed", error=str(e))
        raise EmbeddingError(f"Voyage embedding failed: {e}") from e
    return result.embeddings[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    try:
        result = _client.embed(texts=texts, model=VOYAGE_MODEL)
    except Exception as e:
        log_event(event="embedding_failed", error=str(e))
        raise EmbeddingError(f"Voyage embedding failed: {e}") from e
    return result.embeddings

import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Add it to .env before starting the gateway."
    )

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-haiku-4-5-20251001")

UPSTASH_VECTOR_REST_URL = os.environ.get("UPSTASH_VECTOR_REST_URL")
UPSTASH_VECTOR_REST_TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN")
if not UPSTASH_VECTOR_REST_URL or not UPSTASH_VECTOR_REST_TOKEN:
    raise RuntimeError(
        "UPSTASH_VECTOR_REST_URL/UPSTASH_VECTOR_REST_TOKEN are not set. "
        "Add them to .env before starting the gateway."
    )

VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY")
if not VOYAGE_API_KEY:
    raise RuntimeError("VOYAGE_API_KEY is not set. Add it to .env before starting the gateway.")

VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL", "voyage-3.5")

# Provisional starting point, NOT calibrated. The similarity threshold is the
# project's central tunable (see docs/spec.md sec. 3) and gets fixed by the
# Fase 5 eval sweep, not by this default. See docs/DECISIONS.md "Día 3".
CACHE_SIMILARITY_THRESHOLD = float(os.environ.get("CACHE_SIMILARITY_THRESHOLD", "0.92"))

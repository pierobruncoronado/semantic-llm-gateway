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

# Calibrated via the Fase 5 threshold sweep (23-pair golden set, fp_rate as the
# north-star metric) -- not a default picked by hand. fp_rate=0.00% on the
# golden set, hit_rate=44.44%. See docs/DECISIONS.md "Día 7" for the full
# sweep table and the irreducible overlap finding (max trap score 0.8953 vs
# min genuine-paraphrase score 0.7567) that drove this number.
CACHE_SIMILARITY_THRESHOLD = float(os.environ.get("CACHE_SIMILARITY_THRESHOLD", "0.90"))

# Anti-abuse defaults (spec sec. 4 NFR anti-abuso, sec. 7 caso 5). Conservative
# v1 starting points, not calibrated against real traffic — see
# docs/DECISIONS.md "Día 6" for the reasoning and what would change this.
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
MAX_MESSAGE_CHARS = int(os.environ.get("MAX_MESSAGE_CHARS", "8000"))
MAX_PAYLOAD_BYTES = int(os.environ.get("MAX_PAYLOAD_BYTES", "262144"))

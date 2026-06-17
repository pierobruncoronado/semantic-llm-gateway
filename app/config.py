import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Add it to .env before starting the gateway."
    )

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-haiku-4-5-20251001")

import time

import httpx

GATEWAY_URL = "http://127.0.0.1:8000/v1/messages"


def main() -> None:
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Say 'pong' and nothing else."}],
    }

    start = time.monotonic()
    response = httpx.post(GATEWAY_URL, json=payload, timeout=30.0)
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    print(f"status_code: {response.status_code}")
    print(f"latency_ms: {elapsed_ms}")
    print(f"body: {response.text}")

    response.raise_for_status()


if __name__ == "__main__":
    main()

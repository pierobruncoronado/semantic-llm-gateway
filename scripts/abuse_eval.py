from concurrent.futures import ThreadPoolExecutor

import httpx

GATEWAY_URL = "http://127.0.0.1:8000/v1/messages"
MAX_PAYLOAD_BYTES = 262144
MAX_MESSAGE_CHARS = 8000
RATE_LIMIT_MAX_REQUESTS = 60


def ask(prompt: str, headers: dict | None = None) -> httpx.Response:
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": prompt}],
    }
    return httpx.post(GATEWAY_URL, json=payload, headers=headers, timeout=30.0)


def main() -> None:
    print("=== Caso 5a: mensaje absurdamente largo -> truncado, 200, no tumba el gateway ===")
    long_prompt = "Say 'pong' and nothing else. " + ("filler " * MAX_MESSAGE_CHARS)
    print(f"prompt_length enviado: {len(long_prompt)} chars (> MAX_MESSAGE_CHARS={MAX_MESSAGE_CHARS})")
    r5a = ask(long_prompt, headers={"x-api-key": "abuse-eval-5a"})
    print(f"status_code: {r5a.status_code}")
    assert r5a.status_code == 200, f"esperaba 200, dio {r5a.status_code}: {r5a.text}"

    print()
    print("=== Caso 5b: payload total > MAX_PAYLOAD_BYTES -> 413 ===")
    oversized_prompt = "x" * (MAX_PAYLOAD_BYTES + 1000)
    r5b = ask(oversized_prompt, headers={"x-api-key": "abuse-eval-5b"})
    print(f"status_code: {r5b.status_code}")
    print(f"body: {r5b.text}")
    assert r5b.status_code == 413, f"esperaba 413, dio {r5b.status_code}"

    print()
    print(f"=== Caso 5c: > {RATE_LIMIT_MAX_REQUESTS} requests en <60s con la misma x-api-key -> algún 429 ===")
    # Disparado en paralelo (no secuencial): cada request real toma ~0.5-1.5s
    # (embedding + upstream), así que RATE_LIMIT_MAX_REQUESTS+5 secuenciales
    # tardarían más de RATE_LIMIT_WINDOW_SECONDS y la ventana deslizante
    # iría expirando timestamps viejos antes de cruzar el límite -- no
    # probaría nada. En paralelo, todas caen dentro de la ventana, como
    # ocurriría con una ráfaga real de tráfico.
    headers = {"x-api-key": "abuse-eval-5c"}
    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: ask("ping", headers=headers).status_code, range(RATE_LIMIT_MAX_REQUESTS + 5)))
    blocked = statuses.count(429)
    print(f"status codes: 200={statuses.count(200)} 429={blocked} otros={len(statuses) - statuses.count(200) - blocked}")
    assert blocked > 0, "esperaba al menos un 429 tras exceder el límite"

    print()
    print("=== Control: prompt normal, key sin abusar -> 200, sin marcas ===")
    r_clean = ask("What is the boiling point of water in Celsius?", headers={"x-api-key": "abuse-eval-control"})
    print(f"status_code: {r_clean.status_code}")
    assert r_clean.status_code == 200, f"esperaba 200, dio {r_clean.status_code}"

    print()
    print("Todas las aserciones pasaron.")


if __name__ == "__main__":
    main()

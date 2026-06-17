import httpx

GATEWAY_URL = "http://127.0.0.1:8000/v1/messages"


def ask(prompt: str) -> dict:
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = httpx.post(GATEWAY_URL, json=payload, timeout=30.0)
    response.raise_for_status()
    return response.json()


def main() -> None:
    print("=== Caso 1 (spec 7.1): mismo prompt dos veces -> miss, luego hit ===")
    prompt_1 = "What is the boiling point of water in Celsius?"
    r1a = ask(prompt_1)
    r1b = ask(prompt_1)
    print(f"1st call usage: {r1a['usage']}")
    print(f"2nd call usage: {r1b['usage']}")

    print()
    print("=== Caso 2 (spec 7.2): paráfrasis -> hit semántico ===")
    r2a = ask("¿cuánto cuesta una limpieza?")
    r2b = ask("precio de limpieza dental")
    print(f"Prompt A response: {r2a['content']}")
    print(f"Prompt B response: {r2b['content']}")
    print(
        "(si ambas respuestas son idénticas, fue cache-hit; ver log del server "
        "para similarity_score)"
    )

    print()
    print("=== Caso 3 (spec 7.3, EL TRAP): intención opuesta, superficie similar ===")
    r3a = ask("List the products we DO have in stock.")
    r3b = ask("List the products we do NOT have in stock.")
    print(f"Prompt A ('DO have') response: {r3a['content']}")
    print(f"Prompt B ('do NOT have') response: {r3b['content']}")
    print(
        "(ver log del server: si B dio cache_hit=true, es el falso positivo "
        "documentado en DECISIONS.md con su similarity_score real)"
    )


if __name__ == "__main__":
    main()

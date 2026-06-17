# docs/DECISIONS.md — Bitácora de decisiones

Solo decisiones (qué/por qué/cómo), no narración línea por línea. Referencia: `docs/spec.md`.

## Día 1 — Passthrough crudo

**Qué:** Proxy transparente `POST /v1/messages` (FastAPI) que reenvía a la API de Anthropic vía la abstracción `Provider`, sin cache semántico ni filtro de injection todavía.

**Por qué:** Es la base del flujo (sección 5 de la spec, paso 3 "Provider abstraction"). Caching e injection filter son fases siguientes — implementarlas antes de tener el passthrough probado habría sido construir sobre algo no verificado.

**Cómo:**
- `app/providers/anthropic_provider.py`: `AnthropicProvider` implementa `Provider.complete()` envolviendo `anthropic.AsyncAnthropic`. Traduce `CompletionRequest` → `messages.create()` y la respuesta del SDK → `CompletionResponse`. Errores del SDK (`APIStatusError`, `APIConnectionError`) se capturan y relanzan como `ProviderError` (nunca un crash silencioso).
- `app/main.py`: endpoint `POST /v1/messages` con el mismo shape que la API de Anthropic (para que un cliente como la clínica pueda apuntar aquí sin cambiar su código). Loguea JSON a stdout por request (modelo, tokens in/out, latencia upstream, `cache_hit: false` hardcodeado hasta que exista cache). `ProviderError` se mapea a `HTTPException` con el status_code real del upstream.
- `scripts/smoke_test.py`: hace un POST real contra el gateway corriendo en `127.0.0.1:8000` e imprime status/latencia/body — validación end-to-end con ejecución visible, no solo lectura de código.

**Input → output verificado:**
- Input: `{"model": "claude-haiku-4-5-20251001", "max_tokens": 64, "messages": [{"role": "user", "content": "Say 'pong' and nothing else."}]}`
- Output: `200 OK`, `content: [{"text": "pong", ...}]`, `usage: {input_tokens: 17, output_tokens: 5}`, latencia total ~1.1s (incluye cold start de conexión), latencia upstream loggeada: 968ms.
- Log estructurado emitido: `{"event": "request_complete", "model": "claude-haiku-4-5-20251001", "input_tokens": 17, "output_tokens": 5, "latency_upstream_ms": 968.0, "cache_hit": false}`.

**Gotchas:**
- `httpx` se usa directamente en `smoke_test.py` (ya estaba instalado como dependencia transitiva del SDK de Anthropic) — se agregó explícito a `requirements.txt` porque ahora es una dependencia directa, no solo transitiva.
- `REDIS_URL` todavía no está en `.env` — se agrega en la fase de cache semántico, no antes.

**Pendiente para próxima sesión:** caching semántico (embeddings + Redis + umbral), filtro de injection, instrumentación por etapa (embedding/cache lookup además de upstream), endpoint `/metrics`.

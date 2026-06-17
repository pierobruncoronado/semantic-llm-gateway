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

**Pendiente para próxima sesión:** caching semántico (embeddings + Upstash Vector + umbral), filtro de injection, instrumentación por etapa (embedding/cache lookup además de upstream), endpoint `/metrics`.

## Día 2 — Corrección de la decisión de store (antes de implementar cache)

**Qué:** se reemplaza "Redis con módulo de vectores (RediSearch/Redis Stack)" por **Upstash Vector** como store del cache semántico. `docs/spec.md` secciones 3, 5 y 6 actualizadas.

**Por qué:** la decisión original asumía que Upstash Redis gestionado soporta búsqueda vectorial vía RediSearch/Redis Stack. Verificado contra documentación actual (Context7, jun 2026): la feature "Search" de Upstash Redis es full-text (motor Tantivy), no similitud por coseno sobre embeddings. La búsqueda vectorial real es **Upstash Vector**, un producto serverless separado con su propio índice y credenciales REST (`UPSTASH_VECTOR_REST_URL` / `UPSTASH_VECTOR_REST_TOKEN`). La razón original para elegir Redis ("TTL nativo") tampoco se sostiene del lado de Vector: Upstash Vector no tiene TTL nativo por entrada.

**Cómo (decisión tomada con el owner):** un solo recurso — Upstash Vector. El embedding y la respuesta cacheada van juntos en los `metadata` del mismo vector (no se agrega un segundo store solo por el TTL). Expiración de entradas se maneja en código vía `created_at` en metadata, o se omite en v1 — explícitamente fuera de alcance crítico: el umbral de similitud es el corazón del proyecto, no la expiración. (Alternativa descartada: Vector + Redis combinados, Redis solo para TTL de la respuesta — agrega un segundo recurso/credenciales sin aportar al punto central del proyecto.)

**Gotchas:**
- `CLAUDE.md` (reglas de dominio) actualizado en la misma sesión para reflejar Upstash Vector (ya no dice Redis/TTL).
- Modelo de embeddings: Voyage, `dimension=1024` — ya estaba implícito en la spec ("reúsa el patrón de embeddings del #1", la clínica) y confirmado por el owner.

## Día 3 — Caching semántico: mecanismo cableado + primeros datos reales del umbral

**Qué:** `app/embeddings.py` (Voyage), `app/cache.py` (`SemanticCache` sobre Upstash Vector: `query()`/`store()`), `app/log.py` (helper de logging compartido), y wiring completo en `app/main.py`: extrae el último mensaje de usuario → embed → query contra Upstash Vector → si `score >= threshold` responde desde cache sin llamar a Anthropic; si no, llama al modelo y guarda la respuesta nueva. Latencia instrumentada en 3 etapas separadas (`embedding_ms`, `cache_lookup_ms`, `upstream_ms`) en el log estructurado.

**Umbral usado:** `CACHE_SIMILARITY_THRESHOLD=0.92` (env var, default en `app/config.py`). **Esto es un punto de arranque para poder cablear y probar el mecanismo HOY — no es el umbral calibrado.** La calibración real (sweep de umbrales contra falso-positivo rate medido) es la Fase 5 de evals (spec sección 7) y queda pendiente. No tratar `0.92` como decisión cerrada en ninguna sesión futura sin pasar por ese sweep.

**Degradación elegante verificada en vivo (no simulada):** la cuenta de Voyage usada es free-tier (3 RPM sin método de pago). Al exceder el rate limit a mitad de la corrida de pruebas, `embed()` lanzó `EmbeddingError`, quedó logueado como `{"event": "embedding_failed", "error": "...reduced rate limits of 3 RPM..."}`, y el gateway siguió respondiendo 200 OK vía passthrough directo (sin cache para esas requests) en lugar de caerse. Es exactamente la regla de `CLAUDE.md` ("si el cache cae, el gateway sigue como passthrough") funcionando de verdad, no en teoría.

**Resultados reales medidos — los 3 casos de la spec sección 7:**

1. **Caso 1 (miss → hit, mismo prompt):** primera llamada → miss correcto (índice vacío), `cache.store()` guarda la respuesta. Una consulta posterior con el mismo texto re-embebido dio `similarity_score: 1.0` y cache-hit correcto. **Gotcha real encontrado:** en la corrida automatizada (`scripts/cache_eval.py`), la SEGUNDA llamada —disparada milisegundos después de que la primera terminara— todavía dio miss. Upstash Vector tiene latencia de propagación entre el `upsert` y que el vector quede queryable; en una prueba aislada, esperar ~1s entre `store()` y `query()` fue suficiente para que el hit apareciera consistentemente. **Implicación para v1:** el caching semántico no es instantáneo-instantáneo bajo ráfagas; un cache-hit inmediatamente después del primer write del mismo prompt no está garantizado. No es un bug del código, es una característica de Upstash Vector a tener en cuenta en los evals de Fase 5 (dar margen de propagación entre escritura y lectura).

2. **Caso 2 (paráfrasis, misma intención — "¿cuánto cuesta una limpieza?" vs "precio de limpieza dental"):** `similarity_score = 0.7582`. **Con el umbral 0.92, esto da MISS** — un falso negativo: dos prompts que SÍ deberían compartir respuesta no la comparten. No es el caso que prueba la spec (que pide ver el falso positivo), pero es información real y honesta: 0.92 es lo bastante conservador como para perder hit-rate en paráfrasis genuinas, no solo para evitar falsos positivos.

3. **Caso 3 — EL TRAP (spec 7.3, intención opuesta, superficie similar — "List the products we DO have in stock." vs "List the products we do NOT have in stock."):** `similarity_score = 0.8265`. **Con el umbral 0.92, esto da miss correcto — NO hubo falso positivo en esta corrida.** Pero el dato central para el case study es la comparación entre los dos scores: el par de intención OPUESTA (caso 3, `0.8265`) puntuó MÁS ALTO que el par de paráfrasis genuina en otro idioma (caso 2, `0.7582`). Esto es la advertencia exacta de la spec sección 3 hecha número real: la geometría de embeddings no ordena "similar en superficie" y "mismo significado" de forma consistente — un trap con plantilla casi idéntica puede acercarse más al umbral que una paráfrasis real. **Con cualquier umbral por debajo de `0.8265` (p. ej. 0.80), este mismo par habría producido el falso positivo que describe la spec 7.3** (servir "sí tenemos en stock" como respuesta a "qué NO tenemos en stock") — la prueba concreta de por qué el umbral no se fija a ojo.

**Gotchas:**
- El índice de Upstash Vector quedó con ~4 vectores de prueba de esta sesión (incluye un entry sintético insertado a mano para probar `store()`/`query()` aislado de Anthropic). No se limpió — no afecta evals futuros si se usa una `namespace` separada para los evals formales de Fase 5, pendiente de decidir.
- `cache.store()` y `cache.query()` corren de forma síncrona (SDK de `upstash-vector` es sync) dentro de un endpoint `async def` — no bloquea otras requests porque FastAPI/uvicorn corre un solo worker en esta fase, pero si se agregan más workers o concurrencia real, esto debería pasar a un executor o a un cliente async. No se resuelve hoy — anotado para cuando el throughput importe (no es v1).
- `voyageai.Client.embed()` SÍ es determinístico: dos llamadas separadas con el mismo texto dieron cosine similarity 1.0 entre sí (verificado). El miss del caso 1 (punto anterior) fue por timing/propagación de Upstash, no por no-determinismo del embedding.

**Pendiente para próxima sesión:** filtro de injection (caso 4 y 5 de la spec), endpoint `/metrics`, decidir namespace para evals formales, y la Fase 5 real (sweep de umbral + falso-positivo rate medido en serio, no solo estos 3 puntos de datos).

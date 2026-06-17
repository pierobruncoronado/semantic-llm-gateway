# Reglas del proyecto (leer siempre)

## Contexto
- Proyecto: capa perimetral (gateway) que se interpone entre apps con LLM y el API de Anthropic, con caching semántico, observabilidad de costo/latencia y defensa de prompt-injection. La spec completa está en `docs/spec.md` — es la fuente de verdad. Ante ambigüedad, consultarla; si no resuelve, PREGUNTARME antes de asumir.
- Idioma del producto: N/A (es infraestructura, no conversa). Idioma del código y materiales: EN.

## Flujo de trabajo (obligatorio en cada sesión)
1. Antes de codear: enumerar el plan en pasos y esperar mi OK.
2. Después de implementar: CORRER el código y mostrar el output real. Nada es "listo" sin ejecución visible.
3. Si algo que pido contradice la spec o agranda el alcance v1: avisar y NO implementar sin confirmación.
4. Cerrar cada sesión con:
   (a) verificación contra los criterios de aceptación de la spec;
   (b) actualizar `docs/DECISIONS.md` con la fase trabajada — qué/por qué/cómo, input→output, gotchas (solo decisiones, no narración línea por línea);
   (c) commit descriptivo + verificar `.gitignore` y que no haya secrets + `git push` al remoto;
   (d) dejar los pendientes para la próxima sesión.

## Reglas de dominio (las decisiones de la spec que NO se reescriben)
- **El umbral de similitud del cache es el parámetro CENTRAL del proyecto.** NO se fija a un default arbitrario. Se trata como tunable validado por evals. Razón crítica: la geometría de embeddings no separa de forma confiable paráfrasis genuinas de intenciones distintas — un score alto de similitud NO garantiza que dos prompts quieran la misma respuesta. Un umbral demasiado laxo sirve respuestas equivocadas en silencio (falso positivo). El falso-positivo rate es la métrica estrella, no el hit-rate crudo.
- **Caching SEMÁNTICO, no exact-match.** Embeber el prompt entrante, buscar por coseno en Redis, servir desde cache solo si supera el umbral. Exact-match no es el objetivo.
- **Solo-Anthropic en v1, pero con abstracción `Provider` lista para multi-proveedor.** El adaptador concreto es Anthropic; la interfaz NO debe asumir el proveedor. Multi-proveedor real (OpenAI/Google) es v2 — no implementarlo.
- **Store: Redis (Upstash gestionado).** No pgvector. TTL nativo para expiración de entradas.
- **Defensa de injection pre-call:** filtro que inspecciona el prompt entrante contra patrones de injection conocidos ANTES de llegar al modelo. Bloquea/marca los sospechosos.
- **El gateway es agnóstico al modelo:** el cliente especifica qué modelo quiere. Haiku por defecto solo para el upstream de prueba.
- **Cliente de demo: la clínica** apuntando su URL upstream al gateway, sin cambiar su código.
- **Fuera de alcance v1 (NO tocar):** multi-proveedor real, routing/failover, auth/virtual keys/budgets, dashboard UI, rate limiting distribuido, streaming SSE.

## Estándares técnicos (production-readiness — el filtro de contratación)
- Secrets SOLO en `.env`; verificar `.gitignore` antes del primer commit.
- Manejo de errores en TODA llamada externa (Anthropic, Redis, embeddings): try/except + log + fallback. Nunca un crash silencioso. Si el cache (Redis) cae, el gateway debe seguir funcionando como passthrough directo al modelo — degradación elegante, no caída.
- Validación fail-closed donde aplique.
- Logs estructurados (JSON a stdout), sin contenido de prompt con PII en claro.
- Instrumentar latencia por etapa (embedding / lookup de cache / llamada upstream) — números medidos, no hand-waved.
- Medir tokens reales y calcular costo por request.
- Modelo por defecto: el más barato capaz (Haiku); el cliente puede pedir otro.
- Evals como gate: definir la baseline primero (sección 7 de la spec); correrlas antes de declarar "funciona".
- Funciones cortas, nombres descriptivos, sin abstracciones especulativas.

## Anti-patrones míos (interrumpir si aparecen)
- Refactorizar/embellecer algo que ya funciona antes de terminar la fase → terminado > perfecto.
- Meter features fuera del alcance v1 (sobre todo multi-proveedor real o un dashboard) → señalar la sección "Fuera de alcance" de la spec.
- Pulir el sistema/arquitectura/los docs en vez de shippear el core → decírmelo de frente.

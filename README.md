# Semantic LLM Gateway

A perimeter layer that sits between LLM-powered apps and the Anthropic API. Drop-in
replacement for the Anthropic endpoint — point an existing client's base URL here and
nothing else changes. Adds **semantic caching** (embed the prompt, serve a cached
response on a cosine-similarity hit instead of calling the model again), a **pre-call
prompt-injection filter**, **anti-abuse defenses** (rate limiting, payload caps, input
truncation), and a `/metrics` endpoint — all instrumented with real, measured numbers,
not estimates.

---

## Why semantic, not exact-match

Caching on exact string match misses every paraphrase. Caching on embedding similarity
catches paraphrases — but cosine similarity does **not** reliably separate "same intent,
different wording" from "different intent, similar surface form." A threshold picked by
hand can silently serve the wrong cached answer (a false positive) for a prompt that
*looks* like an earlier one but means something different — e.g. "list what we **do**
have in stock" vs "list what we **don't**."

This project treats the similarity threshold as the central, calibrated parameter of the
system — not a default. `CACHE_SIMILARITY_THRESHOLD=0.90` was chosen via a 23-pair golden-set
sweep (`scripts/threshold_eval.py`) measuring false-positive rate as the north-star metric,
not raw hit-rate. The full sweep table, the irreducible overlap finding (a same-template
opposite-intent pair scored *higher* than a genuine cross-lingual paraphrase), and the
trade-off accepted at `0.90` are documented in
[`docs/DECISIONS.md`](docs/DECISIONS.md) ("Día 7").

---

## Architecture

```
Client (e.g. a clinic's WhatsApp agent)
        │  POST /v1/messages   (same shape as the Anthropic API)
        ▼
┌───────────────────────────────────────────────────────────┐
│  Gateway pipeline                                          │
│                                                              │
│  1. payload cap (413 if body too large)                    │
│  2. rate limit per bucket (x-api-key, fallback to IP)       │
│  3. input truncation (long messages clipped, not rejected)  │
│  4. injection filter (known patterns → 400, hard reject)    │
│  5. embed prompt (Voyage) → query Upstash Vector            │
│       score >= 0.90 ──► serve cached response (no LLM call) │
│       score <  0.90 ──► call Anthropic, cache the response  │
└───────────────────────────────────────────────────────────┘
        │
        ▼
  Anthropic API (model is caller-specified; Haiku is the default for cheap upstream)
```

If Upstash Vector or the embedding call fails, the gateway degrades to a direct
passthrough to Anthropic instead of crashing — caching is an optimization, not a
dependency for correctness.

`Provider` (`app/providers/base.py`) is an abstraction ready for multiple providers;
only the Anthropic adapter is implemented in v1 — see [`docs/spec.md`](docs/spec.md)
for what's explicitly out of scope (multi-provider, routing/failover, auth/virtual keys,
dashboard UI, streaming).

---

## Local setup — clone → run in under 10 minutes

**Prerequisites:** Python 3.11+, an [Anthropic API key](https://console.anthropic.com),
an [Upstash Vector](https://upstash.com) index (cosine similarity), a
[Voyage AI](https://www.voyageai.com) API key.

```bash
git clone https://github.com/pierobruncoronado/semantic-llm-gateway.git
cd semantic-llm-gateway

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt

cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, UPSTASH_VECTOR_REST_URL, UPSTASH_VECTOR_REST_TOKEN, VOYAGE_API_KEY

uvicorn app.main:app --reload
```

```bash
# Health check
curl http://localhost:8000/health

# Real request — passthrough on first call, cache-hit on the second
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":32,"messages":[{"role":"user","content":"What is the boiling point of water in Celsius?"}]}'

# Aggregated metrics
curl http://localhost:8000/metrics
```

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | **yes** | Upstream model calls. |
| `UPSTASH_VECTOR_REST_URL` | **yes** | Semantic cache store (cosine index). |
| `UPSTASH_VECTOR_REST_TOKEN` | **yes** | Upstash Vector REST auth token. |
| `VOYAGE_API_KEY` | **yes** | Embeddings (`voyage-3.5`, 1024-dim) for the cache. |
| `DEFAULT_MODEL` | no (default `claude-haiku-4-5-20251001`) | Used when the caller omits `model`. |
| `CACHE_SIMILARITY_THRESHOLD` | no (default `0.90`) | Calibrated — see "Why semantic, not exact-match" above before changing. |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | no (default `60`/`60`) | Sliding-window rate limit per bucket. |
| `MAX_MESSAGE_CHARS` | no (default `8000`) | Per-message truncation cap. |
| `MAX_PAYLOAD_BYTES` | no (default `262144`) | Whole-request size cap (413 above this). |

---

## Deploy to Railway (24/7, no laptop required)

This repo ships a `Dockerfile` and `railway.json` — Railway's GitHub deploy auto-detects
the Dockerfile, no Procfile/buildpack config needed.

1. Push this repo to GitHub (already at `origin`, see `git remote -v`).
2. In the [Railway dashboard](https://railway.app): **New Project → Deploy from GitHub repo**
   → select `semantic-llm-gateway`.
3. Under the service's **Variables** tab, add the 4 required keys from the table above
   (`ANTHROPIC_API_KEY`, `UPSTASH_VECTOR_REST_URL`, `UPSTASH_VECTOR_REST_TOKEN`,
   `VOYAGE_API_KEY`). Do **not** add a `PORT` variable — Railway injects it, and the
   Dockerfile's `CMD` reads it at container start.
4. Deploy. Railway uses `railway.json`'s `healthcheckPath: /health` to confirm the
   container is up before routing traffic, and `restartPolicyType: ON_FAILURE` to
   restart on crashes.
5. Once deployed, verify against the public URL Railway assigns
   (`https://<your-service>.up.railway.app`):

```bash
curl https://<your-service>.up.railway.app/health
curl https://<your-service>.up.railway.app/metrics
curl -X POST https://<your-service>.up.railway.app/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":32,"messages":[{"role":"user","content":"Say pong and nothing else."}]}'
```

A 200 from all three with the laptop closed/off confirms the acceptance criterion
("desplegado en cloud, responde con la laptop apagada").

**No Postgres session-pooler gotcha here:** unlike the Supabase-backed sibling projects
(clinic, Analyst), the cache store is **Upstash Vector**, a REST/HTTPS service — there's
no database connection pooler, no IPv4/IPv6 distinction, and no prepared-statement mode
to get wrong.

---

## Demo client: the clinic

The [`whatsapp-clinic-agent`](https://github.com/pierobruncoronado/whatsapp-clinic-agent)
project points its upstream Anthropic URL at this gateway's `/v1/messages` — no code
change on the clinic side, since the gateway mirrors the Anthropic request/response shape.

---

## Stack

Python · [FastAPI](https://fastapi.tiangolo.com) · [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) ·
[Upstash Vector](https://upstash.com/docs/vector) (cosine similarity index) ·
[Voyage AI](https://www.voyageai.com) (`voyage-3.5` embeddings) ·
[Railway](https://railway.app) (Docker deploy)

---

## Docs

- [`docs/spec.md`](docs/spec.md) — full specification (source of truth, acceptance criteria)
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decision log: what / why / how, real run evidence, gotchas

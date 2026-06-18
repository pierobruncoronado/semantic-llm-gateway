# Case Study — Semantic LLM Gateway

A perimeter layer for LLM-powered apps: semantic caching, cost/latency observability, and prompt-injection defense — sitting in front of Anthropic's API so client applications don't have to build any of that themselves.

**TL;DR:** A gateway that sits in front of Anthropic's API and adds semantic caching, cost/latency observability, and prompt-injection defense without requiring client apps to change their code. The central technical finding: a 23-pair calibration set shows that cosine similarity alone does not cleanly separate genuine paraphrases from opposite-intent prompts — the highest-scoring "different intent" pair (0.8953) sits *above* the lowest-scoring "same intent" pair (0.7567), so the cache threshold (0.90) is a measured trade-off, not a tuned-to-zero ideal. All 6 v1 phases are built and verified against running code; cloud deployment is implemented and smoke-tested in Docker but not yet live, deferred by a free-tier account quota limit, not a technical gap.

## 1. The problem

A company running several LLM-backed apps in production has no single place to control token cost, observe what's happening per request, or guard against prompt injection. Without a gateway: every app re-implements its own logging, cost leaks are discovered late because no single point measures aggregate spend, and every app is its own attack surface. The industry pattern is to interpose a gateway that gives a standard way to route requests, track cost, and log — without baking infrastructure concerns into each application.

This project is the third in a portfolio that otherwise consists of LLM *applications* (a clinic WhatsApp agent, a SQL analyst agent). This one is deliberately different: it's the **infrastructure/platform** piece — the LLMOps angle. The thing it has to demonstrate isn't "can build an app with AI," it's "can build the layer that makes those apps auditable, cheap, and safe at scale."

## 2. What I built

Six phases, each shipped and verified against running code before moving to the next:

1. **Transparent passthrough** — `POST /v1/messages`, same request/response shape as Anthropic's own API, so a client modeled on the clinic agent (the project's intended demo target) could point its upstream URL at the gateway without touching its own code. What's actually verified is shape-compatibility via direct smoke tests against the gateway — the clinic's live app was never connected to it.
2. **Semantic caching** — embed the incoming prompt (Voyage), query a vector store by cosine similarity, serve the cached response on a match above threshold instead of calling the model.
3. **Prompt-injection filter** — regex heuristics against known injection patterns, run as the first pipeline stage, hard-reject (`400`) before the prompt ever reaches the embedding step or the model.
4. **`GET /metrics`** — aggregate counters: hit-rate, tokens saved, average latency hit vs. miss, injection-blocked count.
5. **Anti-abuse defenses** — payload-size cap, per-bucket rate limiting, oversized-message truncation — protecting the whole downstream pipeline, not just the cache.
6. **Formal evals** — a 23-pair golden set and a threshold sweep that turns "the cache works" into a measured, defensible number.

Scope was held deliberately narrow: Anthropic-only in v1, but behind a `Provider` interface that doesn't assume a single vendor — multi-provider, routing/failover, auth/virtual keys, a dashboard UI, distributed rate limiting, and streaming are all explicitly out of scope for v1 (see `docs/spec.md` §2). None of that was touched.

## 3. Architecture

```
Client (modeled on the clinic agent — integration pattern, not a live connection tested in this build)
        │  POST /v1/messages  (same shape as Anthropic's API)
        ▼
FastAPI gateway  ──►  structured JSON logging (no raw PII)
        │
        ▼
[0. Anti-abuse perimeter]  ──► payload cap → rate limit → input truncation
        │
        ▼
[1. Injection filter]  ──► suspicious ─► reject (400), metric++
        │ clean
        ▼
[2. Semantic cache]
     ├─ embed the incoming prompt (Voyage)
     ├─ query Upstash Vector by cosine similarity
     │       │
     │   match ≥ threshold (0.90)?
     │       ├─ YES ─► return cached response (no model call)
     │       └─ NO ──► continue ▼
     ▼
[3. Provider abstraction]  ──► AnthropicProvider (v1)  ──► Anthropic API
        │                      (interface ready for other providers in v2)
        ▼
[4. Cache the new response]  ──► Upstash Vector
        ▼
   Response → Client
        │
        └──► [5. GET /metrics]: hit-rate, tokens saved, latency hit vs miss, blocked count
```

**On the clinic integration:** the clinic agent (project #1) is the intended demo client — chosen because its repetitive, paraphrased questions are the ideal case for showing off semantic caching. The gateway's request/response shape matches Anthropic's API exactly so that pointing the clinic's upstream URL here would need no code change on its side. That switch was not exercised live in this build; what's verified is shape-compatibility via direct smoke tests against the gateway itself (§6).

**Store: Upstash Vector**, not Redis. The original spec assumed Upstash's managed Redis had vector search via a RediSearch-style module; verifying against current docs (Context7) showed Upstash Redis's "Search" feature is full-text (Tantivy), not cosine similarity over embeddings. Real vector search lives in **Upstash Vector**, a separate serverless product with its own REST credentials. Caught and corrected before writing a line of caching code (Day 2), not after. The cached response is stored directly in the vector's `metadata` — no second store just for that.

## 4. The core finding: cosine similarity does not separate intent from surface form

This is the central technical story of the project — the equivalent of the "first-aid bug" in the clinic case study: the moment that proves judgment, not just a working feature.

**The claim the spec made up front:** embedding geometry doesn't reliably separate genuine paraphrases from different intents. A high similarity score doesn't guarantee two prompts want the same answer. A cache that's too permissive serves wrong answers silently — a false positive — and the false-positive rate, not raw hit-rate, is the metric that matters.

**First real data point (Day 3):** two opposite-intent prompts with near-identical surface structure ("List the products we DO have in stock" / "...do NOT have in stock") scored **0.8265**. A genuine cross-lingual paraphrase from the clinic domain ("¿cuánto cuesta una limpieza?" / "precio de limpieza dental") scored **0.7582** — lower than the opposite-intent trap. That ordering, by itself, is the whole argument: surface similarity and semantic equivalence are not the same axis.

**Formal calibration (Day 7):** a 23-pair golden set (9 pairs that *should* share a cached response, 14 that *should not*) was embedded in a single Voyage batch, and the threshold was swept from 0.60 to 0.97 in steps of 0.01, measuring false-positive rate, false-negative rate, and hit-rate at every point.

The result: the highest-scoring `should_not_share` pair (`p15`, "Can I eat before the procedure?" / "...after the procedure?") scored **0.8953**. The lowest-scoring `should_share` pair (`p01`, the same cross-lingual clinic pair, re-measured) scored **0.7567**. Between **0.7567 and 0.8953** is a zone of irreducible overlap — no threshold in the sweep achieves 0% false positives *and* 0% false negatives at the same time. This isn't a tuning failure; it's the geometry of the embedding space, demonstrated with 23 pairs instead of 2.

**The number chosen — 0.90 — and its explicit cost:**
- `fp_rate = 0.00%`, `fn_rate = 55.56%`, `hit_rate = 44.44%` (4 of 9 genuine paraphrases actually cache; the 5 missed ones score between 0.7567 and 0.8977). That upper figure, 0.8977, is a *paraphrase* score, not a trap score — it's a different quantity from the 0.8953 trap ceiling above, and it happens to sit higher than that ceiling. In other words: one genuine paraphrase scored higher than the worst trap in the set, and was still missed, only because it landed just under the 0.90 cutoff. That's not a contradiction of the overlap range above (which compares the *lowest* paraphrase to the *highest* trap) — it's a second data point showing the same overlap from the other side.
- It strictly dominates the Day 3 provisional value of 0.92: same false-positive rate (0%), but double the hit-rate (44.44% vs. 22.22%) — 0.92 had never had evidence behind it, it was just a wiring placeholder.
- The margin above the highest observed trap is **0.0047** — 0.90 sits barely above 0.8953. That's a known, monitored limit, not a hidden one: a trap not present in this 23-pair set could plausibly score in that gap and produce a false positive this suite wouldn't catch. The owner chose 0.90 over the more conservative 0.92/0.93 alternatives, explicitly trading margin for hit-rate, after seeing the full 38-row sweep table — not before.

That margin is exactly the kind of thing worth saying out loud rather than hiding: it's what makes the rest of the document credible, and it's a concrete thing to monitor in production (does the golden set need to grow? does production traffic surface a trap above 0.8953?).

## 5. Eval methodology — mixed, applied honestly

The threshold decision used three layers of judgment, not one:

- **Deterministic (the real gate):** the sweep itself — pure arithmetic over the 23 precomputed scores, counting false positives/negatives per candidate threshold. No subjectivity.
- **LLM-as-judge (6 of 23 pairs, ~26%):** the genuinely ambiguous pairs — ones a human couldn't confidently hand-label ("What's included in a basic cleaning?" vs. "...deep cleaning?") — were labeled via the already-built `AnthropicProvider`, using a GEval-style rubric (fixed criterion, SAME/DIFFERENT verdict, one-sentence justification). No new eval framework was added for a single layer of judgment in one session — the GEval pattern (criterion + structured reasoning) was replicated by hand instead.
- **Human (the final gate):** the full 38-row table (threshold × fp_rate × fn_rate × hit_rate) was shown to the project owner before any number was written down. The owner picked 0.90 from three presented options (0.90 mathematically optimal, 0.92 with more margin, 0.93 with extra margin at no additional hit-rate cost on this set).

Applying all three layers to a 23-pair set, rather than calling it "mixed methodology" while only ever using one, is itself part of the credibility of the result.

## 6. Results

Numbers below were measured against running code, not estimated.

**Threshold calibration**
| | Provisional (Day 3) | Calibrated (Day 7) |
|---|---|---|
| Value | 0.92 | **0.90** |
| FP rate | 0% | 0% |
| Hit-rate on golden set | 22.22% | 44.44% |
| Evidence behind it | none — wiring placeholder | 23-pair golden set, full sweep, owner sign-off |

**Latency and tokens (`GET /metrics`, single validation run, Day 5):**
- `avg_latency_hit_ms: 1141.6` vs. `avg_latency_miss_ms: 2658.6`
- `tokens_saved: {input_tokens: 26, output_tokens: 32}`
- This run is small by design — it validates the mechanism and proves the instrumentation is wired correctly (every number above ties back to logged per-stage latencies, embedding + cache-lookup for the hit, embedding + cache-lookup + upstream for the miss). What it doesn't claim is throughput at scale: that depends on real traffic and would be read off the same `/metrics` endpoint in production, not re-derived.

**Injection filter (Day 4):**
- 4/4 known attack patterns blocked with `400` (instruction override, system-prompt extraction, role-jailbreak, fake instruction-delimiter), each logged with the matched pattern name.
- 0 false positives on clean traffic.
- Anchored on a real vector, not a hypothetical one: LiteLLM, the leading open-source gateway, accumulated 8 security advisories in 2026 — including a critical SQLi in API-key verification and an auth bypass via host-header injection. A hard reject before the model call is exactly the class of defense that gap calls for.

**Anti-abuse (Day 6):**
- Oversized message (56,029 chars) → truncated to 8,000, request continues (`200`), not rejected.
- Oversized payload (263,239 bytes) → rejected (`413`) before Pydantic parses the body.
- Burst of 65 concurrent requests, same bucket → 60 allowed, 5 rejected (`429`), exactly the configured limit.

**Graceful degradation (verified live, not simulated, Day 3):** the Voyage account used is free-tier (3 RPM). Mid-test, the rate limit was actually hit — `embed()` raised, the failure was logged (`embedding_failed`), and the gateway kept serving `200 OK` via direct passthrough instead of crashing. The "cache falls, gateway survives" rule in the project's own engineering standards was exercised by a real failure, not a fault injection test.

**Deploy:** Docker build (34.8s) and run verified locally end-to-end — `/health` → `200`, `/metrics` → `200`, `/v1/messages` → `200` with a real Anthropic response, secrets confirmed absent from the image (`.dockerignore`). Railway deploy itself was deferred — see §9.

## 7. Decisions and trade-offs

- **Upstash Vector over Redis-with-vector-module:** the original plan assumed a module Upstash's managed Redis doesn't actually have. Caught by checking current docs before writing the caching code, not after shipping it.
- **Hard reject over flag-and-pass for injection:** confirmed with the owner, backed by three pieces of evidence — LiteLLM's own `detect_prompt_injection` returns `400` rather than flagging-and-passing; the spec's data model defines `injection_blocked` as a boolean, not a continuous score; the spec's language explicitly says "blocks," not "marks."
- **Tokens saved, not dollars saved:** a grep of the repo confirmed no per-model pricing table existed anywhere in the code — only mentioned as a future requirement. Reporting a dollar figure would have meant inventing a price. `tokens_saved` is what's actually measured; converting to USD later is a one-line change once a real pricing source exists.
- **Anti-abuse limits as tunables, not final numbers:** 60 req/min, 8,000 chars/message, 256 KB/payload are documented starting points (same pattern as the cache threshold) meant to be recalibrated against real production traffic, not invented and frozen.
- **No new eval framework for one layer of LLM-judge labeling:** researched DeepEval/Promptfoo's GEval pattern, replicated the pattern (criterion + structured verdict + reasoning) by hand against the existing `AnthropicProvider` instead of adding a dependency that wasn't pulling its weight for a single use.

## 8. What's next (v2)

Explicitly out of scope for v1, by design, not by oversight:
- Real multi-provider support (OpenAI, Google, Bedrock) behind the existing `Provider` interface.
- Routing/failover across providers or deployments.
- Auth, virtual keys, and per-team budgets.
- An observability dashboard (today's `/metrics` is JSON-only, by design).
- Distributed (multi-instance) rate limiting — today's is in-process, single-worker.
- Streaming responses (SSE).
- Growing the golden set beyond 23 pairs to shrink the 0.0047 margin around the highest observed trap, and tracking whether production traffic surfaces traps the current set doesn't.

## 9. Honest scope note

Every acceptance criterion in `docs/spec.md` §8 is met except cloud deployment: the repo is deploy-ready (Dockerfile, `railway.json` with a health check, a README with exact dashboard steps), and a real Docker smoke test — build, run, `/health`, `/metrics`, and a live `/v1/messages` call against Anthropic — passed end-to-end locally. What didn't happen is creating the Railway project itself, because the account's free tier already has two other active projects (the clinic agent, the SQL analyst) and the plan doesn't allow a third without an upgrade. That's an account-quota constraint, not a technical failure — the integration is proven; what's missing is one more cloud resource slot. Completing it is a single follow-up session once quota is freed or upgraded: create the project, load four env vars, run the three `curl` checks from the README against the live URL.

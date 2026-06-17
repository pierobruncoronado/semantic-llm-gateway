"""Fase 5 (spec sec. 7): sweep de umbrales del cache semántico contra un golden
set de pares de prompts, para calibrar CACHE_SIMILARITY_THRESHOLD con evidencia
en vez de a ojo. Ver docs/DECISIONS.md "Día 3" (umbral provisional) y "Día 7"
(este sweep).

Metodología (patrón mixto, ver docs/DECISIONS.md "Día 7"):
- Capa determinista: el sweep de umbrales en sí (matemática pura sobre scores).
- Capa LLM-judge: pares "source=judge" no se etiquetan a mano porque la
  intención compartida o no es genuinamente ambigua para un humano a primera
  vista; se le pide veredicto a Claude (vía la misma AnthropicProvider que ya
  usa el gateway) con un rubric estilo GEval (SAME/DIFFERENT + razón).
- Capa humana: la tabla completa (umbral, fp_rate, fn_rate, hit_rate) se
  imprime para que el owner confirme el número antes de escribirlo en
  app/config.py — no se autoselecciona sin ese gate.

No pasa por Upstash Vector ni dispara requests reales al gateway: los prompts
únicos se embeben en un solo batch (embed_batch), y el sweep es aritmética
sobre esos vectores. Evita el límite de 3 RPM de Voyage free-tier y el delay
de propagación de Upstash documentado en "Día 3".
"""

import asyncio
import sys
from dataclasses import dataclass, field

sys.stdout.reconfigure(encoding="utf-8")

from app.config import ANTHROPIC_API_KEY, DEFAULT_MODEL
from app.embeddings import embed_batch
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import CompletionRequest, Message


@dataclass
class Pair:
    id: str
    category: str
    prompt_a: str
    prompt_b: str
    source: str  # "manual" | "judge"
    label: str | None = None  # "should_share" | "should_not_share"
    judge_reasoning: str = field(default="", repr=False)


GOLDEN_SET: list[Pair] = [
    # --- Positivos manuales (paráfrasis genuina, misma intención) ---
    Pair("p01", "paraphrase_crosslingual", "¿cuánto cuesta una limpieza?", "precio de limpieza dental", "manual", "should_share"),
    Pair("p02", "paraphrase", "How much does a teeth cleaning cost?", "What's the price of a dental cleaning?", "manual", "should_share"),
    Pair("p03", "paraphrase", "What are your opening hours?", "When are you open?", "manual", "should_share"),
    Pair("p04", "paraphrase", "Do you accept walk-ins?", "Can I come in without an appointment?", "manual", "should_share"),
    Pair("p05", "paraphrase_factual", "What is the boiling point of water in Celsius?", "At what Celsius temperature does water boil?", "manual", "should_share"),
    Pair("p06", "paraphrase", "How do I reset my password?", "I forgot my password, how do I get a new one?", "manual", "should_share"),
    Pair("p07", "paraphrase_factual", "What's the capital of France?", "Which city is the capital of France?", "manual", "should_share"),
    Pair("p08", "paraphrase_crosslingual", "¿Puedo cancelar mi cita?", "Necesito cancelar la cita que tengo", "manual", "should_share"),
    # --- Positivos via LLM-judge (genuinamente ambiguos para etiquetar a ojo) ---
    Pair("p09", "borderline", "Tell me about your cancellation policy", "What happens if I miss my appointment?", "judge"),
    Pair("p10", "borderline", "Is teeth whitening covered by insurance?", "Does insurance pay for whitening?", "judge"),
    Pair("p11", "borderline", "What forms of payment do you accept?", "Can I pay with credit card?", "judge"),
    # --- Negativos manuales: EL TRAP (intención opuesta, plantilla casi idéntica) ---
    Pair("p12", "trap_opposite_intent", "List the products we DO have in stock.", "List the products we do NOT have in stock.", "manual", "should_not_share"),
    Pair("p13", "trap_opposite_intent", "What treatments are covered by insurance?", "What treatments are NOT covered by insurance?", "manual", "should_not_share"),
    Pair("p14", "trap_opposite_intent", "Show me appointments available this week.", "Show me appointments NOT available this week.", "manual", "should_not_share"),
    Pair("p15", "trap_opposite_intent", "Can I eat before the procedure?", "Can I eat after the procedure?", "manual", "should_not_share"),
    Pair("p16", "trap_opposite_intent", "What is the price BEFORE the discount?", "What is the price AFTER the discount?", "manual", "should_not_share"),
    Pair("p17", "trap_crosslingual", "¿Tienen turno hoy?", "¿Tienen turno mañana?", "manual", "should_not_share"),
    Pair("p18", "trap_different_action", "How do I cancel my appointment?", "How do I reschedule my appointment?", "manual", "should_not_share"),
    # --- Negativos de control (temas no relacionados, sanity check del embedding) ---
    Pair("p19", "control_unrelated", "What is the boiling point of water in Celsius?", "What's your cancellation policy?", "manual", "should_not_share"),
    Pair("p20", "control_unrelated_crosslingual", "¿Cuánto cuesta una limpieza?", "What's the weather like today?", "manual", "should_not_share"),
    # --- Negativos via LLM-judge (borderline: misma plantilla, distinto ítem/alcance) ---
    Pair("p21", "borderline", "What's included in a basic cleaning?", "What's included in a deep cleaning?", "judge"),
    Pair("p22", "borderline", "Is the consultation free?", "Is the X-ray free?", "judge"),
    Pair("p23", "borderline", "Do you have parking?", "Is parking free?", "judge"),
]

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator for a semantic cache layer in front of an LLM API. "
    "Given two user prompts (A and B), decide whether a SINGLE cached answer to "
    "prompt A would be a correct, appropriate answer to serve in response to "
    "prompt B too -- i.e. would both prompts expect the same answer from the "
    "assistant? Answer on the first line with exactly one word: SAME or "
    "DIFFERENT. On the second line, give a one-sentence reason."
)


async def judge_pair(provider: AnthropicProvider, pair: Pair) -> None:
    request = CompletionRequest(
        model=DEFAULT_MODEL,
        messages=[
            Message(
                role="user",
                content=f'Prompt A: "{pair.prompt_a}"\nPrompt B: "{pair.prompt_b}"',
            )
        ],
        max_tokens=100,
        system=JUDGE_SYSTEM_PROMPT,
    )
    response = await provider.complete(request)
    text = "".join(
        block.get("text", "") for block in response.content if block.get("type") == "text"
    ).strip()
    first_line = text.splitlines()[0].strip().upper() if text else ""
    pair.label = "should_share" if first_line.startswith("SAME") else "should_not_share"
    pair.judge_reasoning = text


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b)


async def main() -> None:
    provider = AnthropicProvider(api_key=ANTHROPIC_API_KEY)

    judge_pairs = [p for p in GOLDEN_SET if p.source == "judge"]
    print(f"=== LLM-judge: etiquetando {len(judge_pairs)} pares borderline ===")
    for p in judge_pairs:
        await judge_pair(provider, p)
        print(f"[{p.id}] {p.category} -> {p.label} | {p.judge_reasoning}")

    unique_texts = list(
        dict.fromkeys(t for p in GOLDEN_SET for t in (p.prompt_a, p.prompt_b))
    )
    print(f"\n=== Embebiendo {len(unique_texts)} prompts únicos en un solo batch ===")
    vectors = embed_batch(unique_texts)
    vec_by_text = dict(zip(unique_texts, vectors))
    print("Batch embebido OK.")

    print("\n=== Scores por par ===")
    scored: list[tuple[Pair, float]] = []
    for p in GOLDEN_SET:
        score = cosine_similarity(vec_by_text[p.prompt_a], vec_by_text[p.prompt_b])
        scored.append((p, score))
        print(
            f"[{p.id}] label={p.label:<17} source={p.source:<6} score={score:.4f} "
            f'| A="{p.prompt_a}" | B="{p.prompt_b}"'
        )

    positives = [(p, s) for p, s in scored if p.label == "should_share"]
    negatives = [(p, s) for p, s in scored if p.label == "should_not_share"]
    print(
        f"\nTotal pares: {len(scored)} | positivos (should_share): {len(positives)} "
        f"| negativos (should_not_share): {len(negatives)}"
    )

    print("\n=== Sweep de umbrales ===")
    header = f"{'umbral':>7} | {'fp_rate':>8} | {'fn_rate':>8} | {'hit_rate':>9} | fp/total_neg | fn/total_pos"
    print(header)
    rows = []
    thresholds = [round(0.60 + 0.01 * i, 2) for i in range(38)]  # 0.60..0.97
    for t in thresholds:
        fp = sum(1 for _, s in negatives if s >= t)
        fn = sum(1 for _, s in positives if s < t)
        fp_rate = fp / len(negatives) if negatives else 0.0
        fn_rate = fn / len(positives) if positives else 0.0
        hit_rate = 1 - fn_rate  # TPR sobre positivos: % de paráfrasis genuinas que SÍ cachean
        rows.append((t, fp_rate, fn_rate, hit_rate, fp, fn))
        print(
            f"{t:>7.2f} | {fp_rate:>8.2%} | {fn_rate:>8.2%} | {hit_rate:>9.2%} "
            f"| {fp}/{len(negatives):<10} | {fn}/{len(positives)}"
        )

    min_fp_rate = min(r[1] for r in rows)
    best_at_min_fp = min((r for r in rows if r[1] == min_fp_rate), key=lambda r: r[2])
    print("\n=== Recomendación (FP rate como métrica estrella) ===")
    print(f"FP rate mínimo alcanzable en este golden set: {min_fp_rate:.2%}")
    print(
        f"Umbral recomendado: {best_at_min_fp[0]:.2f} "
        f"(fp_rate={best_at_min_fp[1]:.2%}, fn_rate={best_at_min_fp[2]:.2%}, "
        f"hit_rate={best_at_min_fp[3]:.2%})"
    )
    if min_fp_rate > 0:
        print(
            "ATENCIÓN: ningún umbral del sweep llega a fp_rate=0% sobre este golden "
            "set -- hay overlap entre scores de pares should_share y "
            "should_not_share (ver pares con score más alto en cada grupo arriba). "
            "Esto es el hallazgo central de la Fase 5, no un bug del script."
        )


if __name__ == "__main__":
    asyncio.run(main())

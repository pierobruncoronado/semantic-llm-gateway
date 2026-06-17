import re
from dataclasses import dataclass

# Curated heuristics for known prompt-injection patterns (spec sec. 2 feature 4,
# sec. 7 case 4). Regex-based on purpose: v1 scope is "known patterns", not an
# ML classifier — see docs/spec.md "fuera de alcance".
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,20}\b(instructions?|prompts?|rules?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_extraction",
        re.compile(
            r"\b(reveal|show|print|repeat|leak)\b.{0,20}\b(your|the)\b.{0,20}\b(system prompt|instructions?|rules?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_jailbreak",
        re.compile(
            r"\b(you are now|act as|pretend to be)\b.{0,30}\b(dan|developer mode|no restrictions|unfiltered|jailbreak)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fake_instruction_delimiter",
        re.compile(
            r"(---+|===+)\s*(end of (system )?instructions?|new instructions?)\s*(---+|===+)?",
            re.IGNORECASE,
        ),
    ),
]


@dataclass
class InjectionMatch:
    pattern_name: str


def check_injection(text: str) -> InjectionMatch | None:
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            return InjectionMatch(pattern_name=name)
    return None

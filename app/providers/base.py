from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str
    content: Any


@dataclass
class CompletionRequest:
    model: str
    messages: list[Message]
    max_tokens: int
    system: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionResponse:
    content: Any
    model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class Provider(ABC):
    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        ...

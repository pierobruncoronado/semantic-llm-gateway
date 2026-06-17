import anthropic

from app.providers.base import (
    CompletionRequest,
    CompletionResponse,
    Provider,
    ProviderError,
)


class AnthropicProvider(Provider):
    def __init__(self, api_key: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        try:
            response = await self._client.messages.create(
                model=request.model,
                messages=[
                    {"role": m.role, "content": m.content} for m in request.messages
                ],
                max_tokens=request.max_tokens,
                **({"system": request.system} if request.system else {}),
                **request.extra,
            )
        except anthropic.APIStatusError as e:
            raise ProviderError(
                f"Anthropic API error: {e.message}",
                status_code=e.status_code,
                body=e.body,
            ) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(
                f"Anthropic connection error: {e}", status_code=502
            ) from e

        return CompletionResponse(
            content=[block.model_dump() for block in response.content],
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw=response.model_dump(),
        )

"""LLM access, switchable between OpenAI and Anthropic like meme-bot (design §17).

``get_llm()`` returns ``None`` when no API key is configured; the game then
uses the offline interpreter and narrator, which is enough to test the rules.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .actions import strict_schema

logger = logging.getLogger("everwild.llm")
T = TypeVar("T", bound=BaseModel)


def _env(key: str, default: str) -> str:
    # GitHub Actions passes unset secrets as empty strings
    return os.environ.get(key) or default


class LLM(Protocol):
    name: str

    def text(self, system: str, prompt: str, max_tokens: int = 2000) -> str: ...

    def json(self, system: str, prompt: str, schema: dict, schema_name: str, max_tokens: int = 4000) -> str: ...


class OpenAIClient:
    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.name = f"openai:{model}"

    def _call(self, system: str, prompt: str, max_tokens: int, response_format: dict | None) -> str:
        kwargs = {"response_format": response_format} if response_format else {}
        response = self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            **kwargs,
        )
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            raise RuntimeError(
                f"OpenAI lieferte keinen Text (finish_reason={choice.finish_reason!r}). "
                "Reasoning-Modelle können das Token-Budget aufbrauchen; max_tokens erhöhen."
            )
        return content

    def text(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        return self._call(system, prompt, max_tokens, None)

    def json(self, system: str, prompt: str, schema: dict, schema_name: str, max_tokens: int = 4000) -> str:
        response_format = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}}
        return self._call(system, prompt, max_tokens, response_format)


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.name = f"anthropic:{model}"

    def text(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        response = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def json(self, system: str, prompt: str, schema: dict, schema_name: str, max_tokens: int = 4000) -> str:
        response = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"name": schema_name, "description": "Antwort im vorgegebenen Format", "input_schema": schema}],
            tool_choice={"type": "tool", "name": schema_name},
        )
        block = next(b for b in response.content if b.type == "tool_use")
        return json.dumps(block.input)


def get_llm() -> LLM | None:
    provider = _env("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        return OpenAIClient(key, _env("OPENAI_MODEL", "gpt-5.6-terra")) if key else None
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        return AnthropicClient(key, _env("CLAUDE_MODEL", "claude-sonnet-5")) if key else None
    raise ValueError(f"Unbekannter LLM_PROVIDER: {provider!r} (erwartet 'openai' oder 'anthropic')")


def ask_model(llm: LLM, system: str, prompt: str, model: type[T], *, retries: int = 2, max_tokens: int = 4000) -> T:
    """Asks for JSON matching ``model``; retries with the validation error (§17)."""
    schema = strict_schema(model)
    attempt_prompt = prompt
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        raw = llm.json(system, attempt_prompt, schema, model.__name__, max_tokens=max_tokens)
        try:
            return model.model_validate_json(raw)
        except ValidationError as error:
            last_error = error
            logger.warning("Ungültige LLM-Antwort (Versuch %d): %s", attempt + 1, error)
            attempt_prompt = (
                f"{prompt}\n\nDeine letzte Antwort war ungültig:\n{error}\n"
                "Antworte noch einmal, genau im vorgegebenen Format."
            )
    raise RuntimeError(f"LLM-Antwort nach {retries + 1} Versuchen ungültig: {last_error}")

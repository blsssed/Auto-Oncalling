"""Configuration loading for OpenAI-compatible LLM providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_int,
    required_str,
)


class LlmConfigurationError(RuntimeError):
    """Raised when an LLM provider cannot be configured."""


@dataclass(frozen=True, slots=True)
class LlmProviderConfig:
    """Typed runtime configuration for a configured LLM provider."""

    provider: str
    api_key: str = field(repr=False)
    base_url: str
    chat_model: str
    embedding_model: str
    embedding_dimensions: int
    rerank_model: str
    rerank_url: str
    context_window_tokens: int
    temperature: float
    timeout_seconds: float
    max_retries: int
    embedding_api_key: str = field(default="", repr=False)
    embedding_base_url: str = ""
    rerank_api_key: str = field(default="", repr=False)
    rerank_base_url: str = ""


def load_llm_provider_config(
    config_path: Path | str | None = None,
) -> LlmProviderConfig:
    """Load LLM provider configuration from the repository project config."""
    try:
        raw_config = project_config_section("llm", config_path=config_path)
        api_key = required_str(raw_config, "apiKey")
        base_url = required_str(raw_config, "baseUrl")
        embedding_section = _optional_section(raw_config, "embedding")
        rerank_section = _optional_section(raw_config, "rerank")

        chat_model = required_str(raw_config, "chatModel")
        model_capabilities = raw_config.get("modelCapabilities")
        if not isinstance(model_capabilities, Mapping):
            raise ProjectConfigurationError(
                "Project config field must be an object: modelCapabilities"
            )
        model_profile_raw = cast(Mapping[object, object], model_capabilities).get(chat_model)
        if not isinstance(model_profile_raw, Mapping):
            raise ProjectConfigurationError(
                f"No model capability profile configured for chatModel: {chat_model}"
            )
        model_profile = {
            str(key): value
            for key, value in cast(Mapping[object, object], model_profile_raw).items()
        }

        embedding_model = _optional_str(embedding_section, "model") or required_str(
            raw_config, "embeddingModel"
        )
        embedding_dimensions = _optional_positive_int(
            embedding_section, "dimensions"
        ) or required_int(raw_config, "embeddingDimensions")
        rerank_model = _optional_str(rerank_section, "model") or required_str(
            raw_config, "rerankModel"
        )
        rerank_url = _optional_str(rerank_section, "baseUrl") or required_str(
            raw_config, "rerankUrl"
        )

        return LlmProviderConfig(
            provider=required_str(raw_config, "provider"),
            api_key=api_key,
            base_url=base_url,
            chat_model=chat_model,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            rerank_model=rerank_model,
            rerank_url=rerank_url,
            context_window_tokens=required_int(model_profile, "contextWindowTokens"),
            temperature=required_float(raw_config, "temperature"),
            timeout_seconds=required_float(raw_config, "timeoutSeconds"),
            max_retries=required_int(raw_config, "maxRetries"),
            embedding_api_key=_optional_str(embedding_section, "apiKey") or api_key,
            embedding_base_url=_optional_str(embedding_section, "baseUrl") or base_url,
            rerank_api_key=_optional_str(rerank_section, "apiKey") or api_key,
            rerank_base_url=_optional_str(rerank_section, "baseUrl") or rerank_url,
        )
    except ProjectConfigurationError as exc:
        raise LlmConfigurationError(str(exc)) from exc


def _optional_section(
    raw_config: Mapping[str, object], key: str
) -> Mapping[str, object]:
    value = raw_config.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProjectConfigurationError(f"Project config field must be an object: {key}")
    return cast(Mapping[str, object], value)


def _optional_str(raw_config: Mapping[str, object], key: str) -> str | None:
    value = raw_config.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectConfigurationError(
            f"Project config field must be a string when present: {key}"
        )
    return value.strip() or None


def _optional_positive_int(raw_config: Mapping[str, object], key: str) -> int | None:
    value = raw_config.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectConfigurationError(
            f"Project config field must be a positive integer when present: {key}"
        )
    return value

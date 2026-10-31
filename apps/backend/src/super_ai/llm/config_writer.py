"""Self-service masked LLM configuration view and user-override writer."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from super_ai.llm.config import LlmConfigurationError, load_llm_provider_config
from super_ai.project_config import (
    DEFAULT_PROJECT_CONFIG_PATH,
    ProjectConfigurationError,
    load_project_config,
    user_config_path_for,
)
from super_ai.tracing import load_tracing_settings


class UserConfigInvalidError(RuntimeError):
    """Raised when the existing user override config cannot be parsed."""


class ApiKeyRequiredError(RuntimeError):
    """Raised when no API key is configured and the update does not provide one."""


class LlmConfigApplyError(RuntimeError):
    """Raised when an applied configuration fails validation and is rolled back."""


@dataclass(frozen=True, slots=True)
class LlmConfigUpdate:
    """Editable self-service LLM configuration fields."""

    api_key: str | None
    base_url: str
    chat_model: str
    context_window_tokens: int
    embedding_model: str
    embedding_dimensions: int
    rerank_model: str
    rerank_url: str
    temperature: float
    timeout_seconds: float
    max_retries: int
    langfuse_enabled: bool | None = None
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None


@dataclass(frozen=True, slots=True)
class LlmConfigView:
    """Masked self-service view of the effective LLM configuration."""

    provider: str
    api_key_configured: bool
    api_key_last4: str | None
    base_url: str
    chat_model: str
    context_window_tokens: int | None
    embedding_model: str
    embedding_dimensions: int
    rerank_model: str
    rerank_url: str
    temperature: float
    timeout_seconds: float
    max_retries: int
    langfuse_enabled: bool
    langfuse_host: str | None
    langfuse_public_key_configured: bool
    langfuse_public_key_last4: str | None
    langfuse_secret_key_configured: bool
    langfuse_secret_key_last4: str | None


def load_llm_config_view(config_path: Path | str | None = None) -> LlmConfigView:
    """Return the masked view of the effective LLM configuration.

    The API key is never exposed: only whether it is configured and its last
    four characters are reported. Invalid configurations degrade to a tolerant
    raw view so the self-service UI can still repair them.
    """
    try:
        typed = load_llm_provider_config(config_path)
    except LlmConfigurationError:
        return _degraded_config_view(config_path)
    return LlmConfigView(
        provider=typed.provider,
        api_key_configured=bool(typed.api_key.strip()),
        api_key_last4=_last4(typed.api_key),
        base_url=typed.base_url,
        chat_model=typed.chat_model,
        context_window_tokens=typed.context_window_tokens,
        embedding_model=typed.embedding_model,
        embedding_dimensions=typed.embedding_dimensions,
        rerank_model=typed.rerank_model,
        rerank_url=typed.rerank_url,
        temperature=typed.temperature,
        timeout_seconds=typed.timeout_seconds,
        max_retries=typed.max_retries,
        **_langfuse_view_fields(config_path),
    )


def apply_llm_config_update(
    config_path: Path | str | None,
    update: LlmConfigUpdate,
) -> LlmConfigView:
    """Persist an LLM configuration update into the user override config file.

    Fields are written to whichever key currently provides the effective value
    (nested ``embedding``/``rerank`` sections win over top-level scalars), the
    ``modelCapabilities`` profile is synced for the new chat model, and the
    file is written atomically. The merged configuration is validated after
    writing; on failure the original file content is restored.
    """
    base_path = Path(config_path) if config_path is not None else DEFAULT_PROJECT_CONFIG_PATH
    user_path = user_config_path_for(base_path)

    original_bytes: bytes | None = None
    if user_path.exists():
        original_bytes = user_path.read_bytes()
        try:
            parsed: object = json.loads(original_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UserConfigInvalidError(
                f"Existing user config file is not valid JSON: {user_path}"
            ) from exc
        if not isinstance(parsed, dict):
            raise UserConfigInvalidError(
                f"Existing user config file must be a JSON object: {user_path}"
            )
        user_config = dict(cast(Mapping[str, Any], parsed))
    else:
        user_config = {}

    merged_llm = _merged_llm_section(base_path)
    user_llm = _mutable_section(user_config, "llm")

    api_key = (update.api_key or "").strip()
    if api_key:
        user_llm["apiKey"] = api_key
    elif _non_empty_str(merged_llm.get("apiKey")) is None:
        raise ApiKeyRequiredError(
            "apiKey is required because no API key is configured yet."
        )

    user_llm["baseUrl"] = update.base_url
    user_llm["chatModel"] = update.chat_model
    user_llm["temperature"] = update.temperature
    user_llm["timeoutSeconds"] = update.timeout_seconds
    user_llm["maxRetries"] = update.max_retries

    merged_embedding = _mapping_or_empty(merged_llm.get("embedding"))
    merged_rerank = _mapping_or_empty(merged_llm.get("rerank"))
    _write_string_field(
        user_llm,
        nested_active=_non_empty_str(merged_embedding.get("model")) is not None,
        section_key="embedding",
        nested_key="model",
        top_key="embeddingModel",
        value=update.embedding_model,
    )
    _write_int_field(
        user_llm,
        nested_active=_positive_int(merged_embedding.get("dimensions")) is not None,
        section_key="embedding",
        nested_key="dimensions",
        top_key="embeddingDimensions",
        value=update.embedding_dimensions,
    )
    _write_string_field(
        user_llm,
        nested_active=_non_empty_str(merged_rerank.get("model")) is not None,
        section_key="rerank",
        nested_key="model",
        top_key="rerankModel",
        value=update.rerank_model,
    )
    _write_string_field(
        user_llm,
        nested_active=_non_empty_str(merged_rerank.get("baseUrl")) is not None,
        section_key="rerank",
        nested_key="baseUrl",
        top_key="rerankUrl",
        value=update.rerank_url,
    )

    capabilities = _mutable_section(user_llm, "modelCapabilities")
    profile = _mutable_section(capabilities, update.chat_model)
    profile["contextWindowTokens"] = update.context_window_tokens
    capabilities[update.chat_model] = profile
    user_llm["modelCapabilities"] = capabilities

    user_config["llm"] = user_llm
    _apply_langfuse_update(base_path, user_config, update)

    payload = json.dumps(user_config, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(user_path, payload)

    try:
        load_llm_provider_config(base_path)
        load_tracing_settings(base_path)
    except (LlmConfigurationError, ProjectConfigurationError) as exc:
        _restore_original(user_path, original_bytes)
        raise LlmConfigApplyError(str(exc)) from exc
    return load_llm_config_view(base_path)


def _degraded_config_view(config_path: Path | str | None) -> LlmConfigView:
    raw = _merged_llm_section(config_path)
    embedding = _mapping_or_empty(raw.get("embedding"))
    rerank = _mapping_or_empty(raw.get("rerank"))
    api_key = _non_empty_str(raw.get("apiKey")) or ""
    chat_model = _non_empty_str(raw.get("chatModel")) or ""
    return LlmConfigView(
        provider=_non_empty_str(raw.get("provider")) or "qwen-openai",
        api_key_configured=bool(api_key),
        api_key_last4=_last4(api_key),
        base_url=_non_empty_str(raw.get("baseUrl")) or "",
        chat_model=chat_model,
        context_window_tokens=_context_window_for(raw, chat_model),
        embedding_model=(
            _non_empty_str(embedding.get("model"))
            or _non_empty_str(raw.get("embeddingModel"))
            or ""
        ),
        embedding_dimensions=(
            _positive_int(embedding.get("dimensions"))
            or _positive_int(raw.get("embeddingDimensions"))
            or 0
        ),
        rerank_model=(
            _non_empty_str(rerank.get("model")) or _non_empty_str(raw.get("rerankModel")) or ""
        ),
        rerank_url=(
            _non_empty_str(rerank.get("baseUrl")) or _non_empty_str(raw.get("rerankUrl")) or ""
        ),
        temperature=_number_or_zero(raw.get("temperature")),
        timeout_seconds=_number_or_zero(raw.get("timeoutSeconds")),
        max_retries=_positive_int(raw.get("maxRetries")) or 0,
        **_langfuse_view_fields(config_path),
    )


def _langfuse_view_fields(
    config_path: Path | str | None,
) -> dict[str, Any]:
    """Read the merged langfuse section into masked view fields.

    Both keys are credentials and are never returned: only configured flags and
    last-four characters, mirroring the LLM apiKey masking semantics.
    """
    merged = load_project_config(config_path)
    section = merged.get("langfuse")
    values = _mapping_or_empty(section)
    public_key = _non_empty_str(values.get("publicKey")) or ""
    secret_key = _non_empty_str(values.get("secretKey")) or ""
    return {
        "langfuse_enabled": values.get("enabled") is True,
        "langfuse_host": _non_empty_str(values.get("host")),
        "langfuse_public_key_configured": bool(public_key),
        "langfuse_public_key_last4": _last4(public_key),
        "langfuse_secret_key_configured": bool(secret_key),
        "langfuse_secret_key_last4": _last4(secret_key),
    }


def _apply_langfuse_update(
    base_path: Path,
    user_config: dict[str, Any],
    update: LlmConfigUpdate,
) -> None:
    """Merge Langfuse fields of the update into the user override config.

    Keys follow apiKey write-masking (empty = keep existing). When nothing
    langfuse-related is provided and no section exists yet, the section is left
    untouched so plain LLM updates keep the file minimal.
    """
    merged = load_project_config(base_path)
    merged_section = _mapping_or_empty(merged.get("langfuse"))
    host = (update.langfuse_host or "").strip()
    public_key = (update.langfuse_public_key or "").strip()
    secret_key = (update.langfuse_secret_key or "").strip()

    if (
        update.langfuse_enabled is None
        and not host
        and not public_key
        and not secret_key
        and not merged_section
    ):
        return

    resulting_enabled = (
        update.langfuse_enabled
        if update.langfuse_enabled is not None
        else merged_section.get("enabled") is True
    )
    resulting_public = public_key or _non_empty_str(merged_section.get("publicKey")) or ""
    resulting_secret = secret_key or _non_empty_str(merged_section.get("secretKey")) or ""
    if resulting_enabled and (not resulting_public or not resulting_secret):
        raise ApiKeyRequiredError(
            "publicKey and secretKey are required when Langfuse tracing is enabled."
        )

    section = _mutable_section(user_config, "langfuse")
    section["enabled"] = resulting_enabled
    if host:
        section["host"] = host
    if public_key:
        section["publicKey"] = public_key
    if secret_key:
        section["secretKey"] = secret_key
    user_config["langfuse"] = section


def _merged_llm_section(config_path: Path | str | None) -> Mapping[str, Any]:
    merged = load_project_config(config_path)
    section = merged.get("llm")
    if not isinstance(section, Mapping):
        return {}
    return cast(Mapping[str, Any], section)


def _mutable_section(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, Any], value))
    return {}


def _write_string_field(
    user_llm: dict[str, Any],
    *,
    nested_active: bool,
    section_key: str,
    nested_key: str,
    top_key: str,
    value: str,
) -> None:
    if nested_active:
        section = _mutable_section(user_llm, section_key)
        section[nested_key] = value
        user_llm[section_key] = section
    else:
        user_llm[top_key] = value


def _write_int_field(
    user_llm: dict[str, Any],
    *,
    nested_active: bool,
    section_key: str,
    nested_key: str,
    top_key: str,
    value: int,
) -> None:
    if nested_active:
        section = _mutable_section(user_llm, section_key)
        section[nested_key] = value
        user_llm[section_key] = section
    else:
        user_llm[top_key] = value


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _restore_original(path: Path, original_bytes: bytes | None) -> None:
    if original_bytes is None:
        try:
            path.unlink()
        except OSError:
            pass
    else:
        path.write_bytes(original_bytes)


def _mapping_or_empty(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _non_empty_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _number_or_zero(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _last4(secret: str) -> str | None:
    stripped = secret.strip()
    if len(stripped) < 4:
        return None
    return stripped[-4:]


def _context_window_for(raw: Mapping[str, Any], chat_model: str) -> int | None:
    if not chat_model:
        return None
    capabilities = _mapping_or_empty(raw.get("modelCapabilities"))
    profile = _mapping_or_empty(capabilities.get(chat_model))
    return _positive_int(profile.get("contextWindowTokens"))

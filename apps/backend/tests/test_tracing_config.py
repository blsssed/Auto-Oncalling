"""可选 Langfuse 追踪：配置加载语义。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from super_ai.project_config import ProjectConfigurationError
from super_ai.tracing import (
    DEFAULT_LANGFUSE_HOST,
    LangfuseTracingProvider,
    load_tracing_settings,
)


def _write_config(tmp_path: Path, langfuse: object) -> Path:
    path = tmp_path / "project.json"
    path.write_text(
        json.dumps({"langfuse": langfuse} if langfuse is not None else {}),
        encoding="utf-8",
    )
    return path


def test_missing_section_disables_tracing(tmp_path: Path) -> None:
    assert load_tracing_settings(config_path=_write_config(tmp_path, None)) is None


def test_disabled_section_disables_tracing(tmp_path: Path) -> None:
    settings = load_tracing_settings(
        config_path=_write_config(
            tmp_path, {"enabled": False, "publicKey": "pk", "secretKey": "sk"}
        )
    )
    assert settings is None


def test_enabled_with_empty_keys_raises_without_leaking_values(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigurationError) as excinfo:
        load_tracing_settings(
            config_path=_write_config(tmp_path, {"enabled": True, "publicKey": "", "secretKey": ""})
        )
    assert "pk-test" not in str(excinfo.value)


def test_enabled_with_full_config_uses_settings(tmp_path: Path) -> None:
    settings = load_tracing_settings(
        config_path=_write_config(
            tmp_path,
            {
                "enabled": True,
                "publicKey": "pk-test",
                "secretKey": "sk-test",
                "host": "https://langfuse.example.test",
            },
        )
    )
    assert settings is not None
    assert settings.public_key == "pk-test"
    assert settings.secret_key == "sk-test"
    assert settings.host == "https://langfuse.example.test"


def test_enabled_without_host_falls_back_to_default(tmp_path: Path) -> None:
    settings = load_tracing_settings(
        config_path=_write_config(
            tmp_path, {"enabled": True, "publicKey": "pk", "secretKey": "sk"}
        )
    )
    assert settings is not None
    assert settings.host == DEFAULT_LANGFUSE_HOST


def test_non_bool_enabled_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigurationError):
        load_tracing_settings(config_path=_write_config(tmp_path, {"enabled": "yes"}))


def test_non_mapping_section_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigurationError):
        load_tracing_settings(config_path=_write_config(tmp_path, "enabled"))


def test_build_provider_returns_none_when_disabled(tmp_path: Path) -> None:
    from super_ai.tracing import build_tracing_provider

    assert build_tracing_provider(config_path=_write_config(tmp_path, None)) is None


def test_build_provider_returns_provider_when_enabled(tmp_path: Path) -> None:
    from super_ai.tracing import build_tracing_provider

    provider = build_tracing_provider(
        config_path=_write_config(
            tmp_path, {"enabled": True, "publicKey": "pk", "secretKey": "sk"}
        )
    )
    assert isinstance(provider, LangfuseTracingProvider)

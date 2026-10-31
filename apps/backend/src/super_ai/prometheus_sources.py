"""Owner-scoped Prometheus 数据源管理与查询代理。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

from super_ai.memory.repositories import (
    MemoryRepositories,
    PrometheusSourceRecord,
    PrometheusSourceRepository,
)
from super_ai.metrics import HttpPromqlProvider, MetricQueryError, MetricSeries

# Prometheus 标识符字符集（label 名 / 指标名），`__name__` 天然被覆盖。
_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")

# 单次 range 查询允许的最大时间跨度（秒）：3 天。
_MAX_RANGE_SPAN_SECONDS = 3 * 24 * 3600
_MAX_QUERY_LENGTH = 4000


@dataclass(frozen=True, slots=True)
class PrometheusSourceError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _ValidatedSource:
    name: str
    base_url: str
    timeout_seconds: int
    max_series: int


def _validated_source(
    name: str,
    base_url: str,
    timeout_seconds: int,
    max_series: int,
) -> _ValidatedSource:
    normalized_name = name.strip()
    normalized_url = base_url.strip()
    parsed = urlsplit(normalized_url)
    if not normalized_name or len(normalized_name) > 120:
        raise PrometheusSourceError("VALIDATION_INVALID_ARGUMENT", "数据源名称无效。")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise PrometheusSourceError(
            "VALIDATION_INVALID_ARGUMENT",
            "数据源地址必须是安全的 HTTP 地址。",
        )
    if not 1 <= timeout_seconds <= 300 or not 1 <= max_series <= 100:
        raise PrometheusSourceError("VALIDATION_INVALID_ARGUMENT", "超时或序列上限参数无效。")
    return _ValidatedSource(
        name=normalized_name,
        base_url=normalized_url,
        timeout_seconds=timeout_seconds,
        max_series=max_series,
    )


class PrometheusSourceService:
    def __init__(
        self,
        repositories: MemoryRepositories,
        *,
        seed_name: str = "本机 Prometheus",
        seed_base_url: str | None = None,
        seed_timeout_seconds: int = 10,
        seed_max_series: int = 20,
    ) -> None:
        self._repositories = repositories
        self._seed_name = seed_name
        self._seed_base_url = seed_base_url
        self._seed_timeout_seconds = seed_timeout_seconds
        self._seed_max_series = seed_max_series

    def _repository(self) -> PrometheusSourceRepository:
        repository = self._repositories.prometheus_sources
        if repository is None:
            raise PrometheusSourceError("SYSTEM_UNAVAILABLE", "Prometheus 数据源存储不可用。")
        return repository

    async def list(self, *, owner_user_id: str) -> list[PrometheusSourceRecord]:
        """列出当前用户的数据源；首次为空且配置了本机地址时自动播种。"""
        repository = self._repository()
        records = await repository.list(owner_user_id=owner_user_id)
        if records:
            return records
        if not self._seed_base_url:
            return records
        try:
            await repository.create(
                owner_user_id=owner_user_id,
                source_id=f"prom_{uuid4().hex}",
                name=self._seed_name,
                base_url=self._seed_base_url,
                username=None,
                password=None,
                enabled=True,
                timeout_seconds=self._seed_timeout_seconds,
                max_series=self._seed_max_series,
            )
        except Exception:  # 播种失败不阻断列表，只回退为空。
            return records
        return await repository.list(owner_user_id=owner_user_id)

    async def create(
        self,
        *,
        owner_user_id: str,
        name: str,
        base_url: str,
        username: str | None,
        password: str | None,
        enabled: bool,
        timeout_seconds: int,
        max_series: int,
    ) -> PrometheusSourceRecord:
        values = _validated_source(name, base_url, timeout_seconds, max_series)
        normalized_username, normalized_password = _normalized_credentials(username, password)
        if (normalized_username is None) != (normalized_password is None):
            raise PrometheusSourceError(
                "VALIDATION_INVALID_ARGUMENT",
                "认证用户名与密码必须同时提供。",
            )
        repository = self._repository()
        records = await repository.list(owner_user_id=owner_user_id)
        if any(record.name == values.name for record in records):
            raise PrometheusSourceError("BUSINESS_CONFLICT", "同名数据源已存在。")
        return await repository.create(
            owner_user_id=owner_user_id,
            source_id=f"prom_{uuid4().hex}",
            name=values.name,
            base_url=values.base_url,
            username=normalized_username,
            password=normalized_password,
            enabled=enabled,
            timeout_seconds=values.timeout_seconds,
            max_series=values.max_series,
        )

    async def update(
        self,
        *,
        owner_user_id: str,
        source_id: str,
        name: str,
        base_url: str,
        username: str | None,
        password: str | None,
        enabled: bool,
        timeout_seconds: int,
        max_series: int,
    ) -> PrometheusSourceRecord:
        values = _validated_source(name, base_url, timeout_seconds, max_series)
        repository = self._repository()
        existing = await repository.get(owner_user_id=owner_user_id, source_id=source_id)
        if existing is None:
            raise PrometheusSourceError("AUTH_FORBIDDEN", "数据源不存在或不可访问。")
        # 空 password = 保留旧值，这样更新表单不必回显密码。
        effective_username = username.strip() if username else existing.username
        effective_password = password if password else existing.password
        if (effective_username is None) != (effective_password is None):
            raise PrometheusSourceError(
                "VALIDATION_INVALID_ARGUMENT",
                "认证用户名与密码必须同时提供。",
            )
        records = await repository.list(owner_user_id=owner_user_id)
        if any(record.name == values.name and record.id != source_id for record in records):
            raise PrometheusSourceError("BUSINESS_CONFLICT", "同名数据源已存在。")
        updated = await repository.update(
            owner_user_id=owner_user_id,
            source_id=source_id,
            name=values.name,
            base_url=values.base_url,
            username=effective_username,
            password=effective_password,
            enabled=enabled,
            timeout_seconds=values.timeout_seconds,
            max_series=values.max_series,
        )
        if updated is None:
            raise PrometheusSourceError("AUTH_FORBIDDEN", "数据源不存在或不可访问。")
        return updated

    async def delete(self, *, owner_user_id: str, source_id: str) -> bool:
        return await self._repository().delete(
            owner_user_id=owner_user_id,
            source_id=source_id,
        )

    async def check(self, *, owner_user_id: str, source_id: str) -> PrometheusSourceRecord:
        """探测数据源：执行一次 instant ``up`` 查询并持久化结果。"""
        repository = self._repository()
        record = await repository.get(owner_user_id=owner_user_id, source_id=source_id)
        if record is None:
            raise PrometheusSourceError("AUTH_FORBIDDEN", "数据源不存在或不可访问。")
        ok = True
        error: str | None = None
        try:
            await _provider_from_record(record).query(query="up")
        except MetricQueryError:
            ok = False
            # 固定文案，避免泄漏上游 URL 或响应体细节。
            error = "Prometheus 数据源不可用。"
        updated = await repository.save_check(
            owner_user_id=owner_user_id,
            source_id=source_id,
            ok=ok,
            error=error,
        )
        if updated is None:
            raise PrometheusSourceError("AUTH_FORBIDDEN", "数据源不存在或不可访问。")
        return updated

    async def label_values(
        self, *, owner_user_id: str, source_id: str, label: str
    ) -> tuple[PrometheusSourceRecord, list[str]]:
        if not _IDENTIFIER_PATTERN.match(label) or len(label) > 120:
            raise PrometheusSourceError("VALIDATION_INVALID_ARGUMENT", "label 名称无效。")
        record, provider = await self._provider_for(
            owner_user_id=owner_user_id, source_id=source_id
        )
        try:
            values = await provider.label_values(label)
        except MetricQueryError as exc:
            raise PrometheusSourceError(
                "SYSTEM_UNAVAILABLE",
                "Prometheus 查询失败，请检查数据源。",
            ) from exc
        return record, values

    async def query_instant(
        self,
        *,
        owner_user_id: str,
        source_id: str,
        query: str,
        at_seconds: float | None,
    ) -> tuple[PrometheusSourceRecord, list[MetricSeries]]:
        _validate_query_text(query)
        record, provider = await self._provider_for(
            owner_user_id=owner_user_id, source_id=source_id
        )
        try:
            series = await provider.query(query=query, at_seconds=at_seconds)
        except MetricQueryError as exc:
            raise PrometheusSourceError(
                "SYSTEM_UNAVAILABLE",
                "Prometheus 查询失败，请检查数据源。",
            ) from exc
        return record, series

    async def query_range(
        self,
        *,
        owner_user_id: str,
        source_id: str,
        query: str,
        start_seconds: float,
        end_seconds: float,
        step_seconds: int,
    ) -> tuple[PrometheusSourceRecord, list[MetricSeries]]:
        _validate_query_text(query)
        if step_seconds < 5 or step_seconds > 300:
            raise PrometheusSourceError(
                "VALIDATION_INVALID_ARGUMENT",
                "stepSeconds 必须在 5-300 之间。",
            )
        if start_seconds >= end_seconds:
            raise PrometheusSourceError(
                "VALIDATION_INVALID_ARGUMENT",
                "开始时间必须早于结束时间。",
            )
        if end_seconds - start_seconds > _MAX_RANGE_SPAN_SECONDS:
            raise PrometheusSourceError(
                "VALIDATION_INVALID_ARGUMENT",
                "查询跨度不能超过 3 天。",
            )
        record, provider = await self._provider_for(
            owner_user_id=owner_user_id, source_id=source_id
        )
        try:
            series = await provider.query_range(
                query=query,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                step_seconds=step_seconds,
            )
        except MetricQueryError as exc:
            raise PrometheusSourceError(
                "SYSTEM_UNAVAILABLE",
                "Prometheus 查询失败，请检查数据源。",
            ) from exc
        return record, series

    async def _provider_for(
        self, *, owner_user_id: str, source_id: str
    ) -> tuple[PrometheusSourceRecord, HttpPromqlProvider]:
        record = await self._repository().get(
            owner_user_id=owner_user_id,
            source_id=source_id,
        )
        if record is None:
            raise PrometheusSourceError("AUTH_FORBIDDEN", "数据源不存在或不可访问。")
        if not record.enabled:
            raise PrometheusSourceError("BUSINESS_CONFLICT", "数据源已停用，无法执行查询。")
        return record, _provider_from_record(record)


def _provider_from_record(record: PrometheusSourceRecord) -> HttpPromqlProvider:
    return HttpPromqlProvider(
        base_url=record.base_url,
        timeout_seconds=float(record.timeout_seconds),
        username=record.username,
        password=record.password,
        max_series=record.max_series,
    )


def _normalized_credentials(
    username: str | None,
    password: str | None,
) -> tuple[str | None, str | None]:
    normalized_username = username.strip() if username else None
    normalized_password = password or None
    return normalized_username, normalized_password


def _validate_query_text(query: str) -> None:
    if not query.strip() or len(query) > _MAX_QUERY_LENGTH:
        raise PrometheusSourceError("VALIDATION_INVALID_ARGUMENT", "PromQL 语句无效。")

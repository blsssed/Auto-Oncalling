"""监控链路第 1 层：PromQL 指标查询与证据摘要。

链路位置：AIOps _run_promql_query / Executor → 本模块 → metric 类型证据
上游调用：AiopsDiagnosticService._run_promql_query
下游消费：诊断证据 payload、报告中的指标文本与统计
设计约束：
- 只接受 Prometheus-compatible HTTP API，不引入第二套查询语言；
- 结果按 max_series 截断，避免大查询撑爆上下文和数据库；
- 未配置或配置非法时由上层降级为纯日志诊断，不阻断任务。

【学习路线 · 监控链路支撑层】站点定位：第 2 站 _executor 的指标数据源。
重点函数：HttpPromqlProvider.query_range。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote

import httpx

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_int,
    required_str,
)

logger = logging.getLogger(__name__)

# label values 响应的有界截断，防止超大 label cardinality 撑爆内存。
_MAX_LABEL_VALUES = 1000


class MetricQueryError(RuntimeError):
    """PromQL 查询不可用或响应非法时抛出的边界异常。

    可选指标能力失败时应由上层降级，不应让整个诊断任务失败。
    """


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """一条命名时间序列：metric labels + (timestamp, value) 样本元组。"""

    metric: dict[str, str]
    values: tuple[tuple[float, float], ...]


class PromqlProvider(Protocol):
    """PromQL 查询边界：range 用于时间窗，instant 用于单点快照。"""

    async def query_range(
        self,
        *,
        query: str,
        start_seconds: float,
        end_seconds: float,
        step_seconds: int,
    ) -> list[MetricSeries]:
        """返回时间窗内的 matrix 序列；step 过小由实现方兜底。"""
        ...

    async def query(self, *, query: str, at_seconds: float | None = None) -> list[MetricSeries]:
        """返回某一时刻的 instant-vector 序列；时间为空表示“现在”。"""
        ...


@dataclass(frozen=True, slots=True)
class HttpPromqlProvider:
    """通过一个 Prometheus-compatible HTTP API 执行 PromQL。"""

    base_url: str
    timeout_seconds: float
    username: str | None = None
    password: str | None = None
    max_series: int = 20
    transport: httpx.AsyncBaseTransport | None = None

    async def query_range(
        self,
        *,
        query: str,
        start_seconds: float,
        end_seconds: float,
        step_seconds: int,
    ) -> list[MetricSeries]:
        """调用 /api/v1/query_range，返回区间 matrix。"""
        payload = await self._get(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": f"{start_seconds:.3f}",
                "end": f"{end_seconds:.3f}",
                # Prometheus 不接受 0/负 step，这里兜底为 1 秒。
                "step": str(max(1, step_seconds)),
            },
        )
        return _parse_result(payload, self.max_series)

    async def query(self, *, query: str, at_seconds: float | None = None) -> list[MetricSeries]:
        """调用 /api/v1/query，返回单点 instant vector。"""
        params = {"query": query}
        if at_seconds is not None:
            params["time"] = f"{at_seconds:.3f}"
        payload = await self._get("/api/v1/query", params=params)
        return _parse_result(payload, self.max_series)

    async def label_values(self, label: str) -> list[str]:
        """调用 /api/v1/label/{label}/values，返回该 label 的取值列表。

        ``__name__`` 即指标名列表；结果有界截断，供指标浏览器做选择器。
        """
        payload = await self._get(
            f"/api/v1/label/{quote(label, safe='')}/values",
            params={},
        )
        return _parse_label_values(payload, _MAX_LABEL_VALUES)

    async def _get(self, path: str, *, params: Mapping[str, str]) -> object:
        """执行一次 HTTP GET 并解析 JSON；错误统一转为 MetricQueryError。"""
        # 与告警源一致：只有 username/password 同时存在才启用 BasicAuth。
        auth = (
            httpx.BasicAuth(self.username, self.password)
            if self.username is not None and self.password is not None
            else None
        )
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
                auth=auth,
            ) as client:
                response = await client.get(url, params=dict(params))
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MetricQueryError("The configured Prometheus provider is unavailable.") from exc


def build_promql_provider(*, config_path: Path | str | None = None) -> PromqlProvider:
    """从项目配置构建 PromQL provider；非法配置转成 MetricQueryError。

    这是可选能力：调用方捕获后应继续纯日志诊断，而不是让任务失败。
    """
    try:
        config = project_config_section("prometheus", config_path=config_path)
        base_url = required_str(config, "baseUrl")
        timeout_seconds = required_float(config, "timeoutSeconds")
        username = _optional_str(config, "username")
        password = _optional_str(config, "password")
        max_series = _optional_positive_int(config, "maxSeries", default=20)
    except ProjectConfigurationError as exc:
        raise MetricQueryError("The configured Prometheus provider is invalid.") from exc
    # 半配置凭据会导致认证行为不可预测，直接判定配置错误。
    if (username is None) != (password is None):
        raise MetricQueryError("Prometheus credentials must include username and password.")
    return HttpPromqlProvider(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        username=username,
        password=password,
        max_series=max_series,
    )


def render_metric_text(series: list[MetricSeries]) -> str:
    """把序列渲染成有界、可引用的文本摘要。

    空序列不是错误，返回明确的中文“无序列”提示，供报告直接引用。
    """
    lines: list[str] = []
    for item in series:
        labels = (
            ",".join(f"{key}={value}" for key, value in sorted(item.metric.items()))
            if item.metric
            else "(no labels)"
        )
        name = item.metric.get("__name__", "series")
        if not item.values:
            lines.append(f"{name}{{{labels}}}: no samples")
            continue
        numbers = [value for _, value in item.values]
        latest = item.values[-1][1]
        lines.append(
            f"{name}{{{labels}}}: latest={latest:.6g} min={min(numbers):.6g} "
            f"max={max(numbers):.6g} avg={sum(numbers) / len(numbers):.6g} "
            f"points={len(item.values)}"
        )
    return "\n".join(lines) or "查询未返回任何指标序列。"


def series_statistics(series: list[MetricSeries]) -> list[dict[str, object]]:
    """把序列投影成证据 payload 使用的逐序列统计（latest/min/max/avg）。"""
    stats: list[dict[str, object]] = []
    for item in series:
        numbers = [value for _, value in item.values]
        entry: dict[str, object] = {
            "metric": item.metric,
            "pointCount": len(item.values),
        }
        if numbers:
            entry["latest"] = item.values[-1][1]
            entry["min"] = min(numbers)
            entry["max"] = max(numbers)
            entry["avg"] = sum(numbers) / len(numbers)
            entry["latestAt"] = item.values[-1][0]
        stats.append(entry)
    return stats


def _parse_label_values(payload: object, max_values: int) -> list[str]:
    """校验 label values 响应信封并返回有界字符串列表。"""
    root = _object_mapping(payload)
    if root.get("status") != "success":
        raise MetricQueryError("The configured Prometheus provider returned an invalid response.")
    data = root.get("data")
    if not isinstance(data, list):
        raise MetricQueryError("The configured Prometheus provider returned an invalid response.")
    values: list[str] = []
    for item in cast(list[object], data):
        if isinstance(item, str) and item:
            values.append(item)
            if len(values) >= max_values:
                break
    return values


def _parse_result(payload: object, max_series: int) -> list[MetricSeries]:
    """校验 Prometheus 成功信封，并把 result 数组转换为有界序列列表。

    非对象序列直接跳过；达到 max_series 后停止读取，防止超大响应用尽内存。
    """
    root = _object_mapping(payload)
    if root.get("status") != "success":
        raise MetricQueryError("The configured Prometheus provider returned an invalid response.")
    data = _object_mapping(root.get("data"))
    result = data.get("result")
    if not isinstance(result, list):
        raise MetricQueryError("The configured Prometheus provider returned an invalid response.")
    series: list[MetricSeries] = []
    for item in cast(list[object], result):
        if not isinstance(item, Mapping):
            continue
        mapping = cast(Mapping[str, object], item)
        metric = _string_mapping(mapping.get("metric"))
        values = _parse_samples(mapping)
        series.append(MetricSeries(metric=metric, values=values))
        if len(series) >= max_series:
            break
    return series


def _parse_samples(item: Mapping[str, object]) -> tuple[tuple[float, float], ...]:
    """解析样本数组：matrix 用 values，instant vector 用单个 value。"""
    # Matrix results carry ``values``; instant-vector results carry one ``value``.
    raw_values = item.get("values")
    candidates: list[object]
    if isinstance(raw_values, list):
        candidates = cast(list[object], raw_values)
    else:
        single = item.get("value")
        candidates = [single] if isinstance(single, list) else []
    samples: list[tuple[float, float]] = []
    for sample in candidates:
        # 单条格式错误只丢该样本，不放弃整条序列。
        if not isinstance(sample, list):
            continue
        sample_items = cast(list[object], sample)
        if len(sample_items) != 2:
            continue
        timestamp, raw_value = sample_items[0], sample_items[1]
        if not isinstance(timestamp, (int, float)):
            continue
        try:
            value = float(cast(str | int | float, raw_value))
        except (TypeError, ValueError):
            continue
        samples.append((float(timestamp), value))
    return tuple(samples)


def _object_mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in cast(dict[object, object], value).items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _optional_str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ProjectConfigurationError(f"Prometheus config field must be a string: {key}")
    return value.strip()


def _optional_positive_int(source: Mapping[str, object], key: str, *, default: int) -> int:
    """可选的严格正整数配置；缺失或非法时静默回退默认值。"""
    value = source.get(key)
    if value is None:
        return default
    try:
        resolved = required_int(source, key)
    except ProjectConfigurationError:
        return default
    return resolved if resolved > 0 else default

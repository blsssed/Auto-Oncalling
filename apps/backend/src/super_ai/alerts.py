"""监控链路第 1 层：活跃告警采集与归一化。

链路位置：alert_poll job / GET /aiops/alerts/active → 本模块 → 快照表 + 自动诊断
上游调用：api/app.py 的 _active_alert_provider 与 _alert_poll_job_handler
下游消费：SQLiteActiveAlertRepository.replace_snapshot、AlertDiagnosisEntry
设计约束：
- 只保留 active/firing 告警，统一成 ActiveAlert；
- 单个 source 失败只跳过该 source，全部失败才抛 AlertProviderError；
- 响应异常只给出安全错误文本，不把上游响应体写进日志或 API。

【学习路线 · 监控链路支撑层】站点定位：第 1 站后台告警轮询
（_alert_poll_job_handler）与第 0 站告警快照接口的数据源。重点：
AggregatedAlertProvider。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import httpx

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_str,
)

logger = logging.getLogger(__name__)


class AlertProviderError(RuntimeError):
    """告警源不可用或响应非法时抛出的边界异常。

    轮询 handler 捕获后保留上一版快照，避免把“查询失败”显示成“没有告警”。
    """


@dataclass(frozen=True, slots=True)
class ActiveAlert:
    """跨厂商统一的活跃告警 DTO。

    原始告警保存在 context 中，并附加 alertSource/alertSourceType 用于溯源；
    labels/annotations 只保留字符串值，避免把任意 JSON 带进快照表。
    """

    id: str
    source: str
    alert_name: str
    service: str
    severity: str
    status: str
    starts_at: str
    summary: str
    labels: dict[str, str]
    annotations: dict[str, str]
    context: dict[str, object]


class ActiveAlertProvider(Protocol):
    """活跃告警读取边界；业务层只依赖本协议，不认识具体厂商。"""

    async def list_active_alerts(self) -> list[ActiveAlert]:
        """返回当前活跃告警；失败时抛 AlertProviderError。"""
        ...


@dataclass(frozen=True, slots=True)
class AlertmanagerAlertProvider:
    """读取一个 Alertmanager v2 告警端点。

    v2 响应顶层直接是告警数组；认证与超时统一交给 _read_json。
    """

    alerts_api: str
    timeout_seconds: float
    source_id: str = "alertmanager"
    username: str | None = None
    password: str | None = None
    transport: httpx.AsyncBaseTransport | None = None

    async def list_active_alerts(self) -> list[ActiveAlert]:
        payload = await _read_json(
            alerts_api=self.alerts_api,
            timeout_seconds=self.timeout_seconds,
            username=self.username,
            password=self.password,
            transport=self.transport,
        )
        if not isinstance(payload, list):
            raise AlertProviderError("The configured alert provider returned an invalid response.")
        return _normalized_alerts(
            cast(list[object], payload),
            source_id=self.source_id,
            source_type="alertmanager-v2",
        )


@dataclass(frozen=True, slots=True)
class PrometheusAlertProvider:
    """读取一个 Prometheus v1 告警端点。

    v1 响应是 {status, data: {alerts: [...]}} 信封，必须同时校验
    status == "success" 与 data.alerts 的类型。
    """

    alerts_api: str
    timeout_seconds: float
    source_id: str = "prometheus"
    username: str | None = None
    password: str | None = None
    transport: httpx.AsyncBaseTransport | None = None

    async def list_active_alerts(self) -> list[ActiveAlert]:
        payload = await _read_json(
            alerts_api=self.alerts_api,
            timeout_seconds=self.timeout_seconds,
            username=self.username,
            password=self.password,
            transport=self.transport,
        )
        root = _object_mapping(payload)
        data = _object_mapping(root.get("data"))
        raw_alerts = data.get("alerts")
        if root.get("status") != "success" or not isinstance(raw_alerts, list):
            raise AlertProviderError("The configured alert provider returned an invalid response.")
        return _normalized_alerts(
            cast(list[object], raw_alerts),
            source_id=self.source_id,
            source_type="prometheus-v1",
        )


@dataclass(frozen=True, slots=True)
class AggregatedAlertProvider:
    """聚合多个告警源，允许部分成功。

    只要至少一个 source 成功就返回其结果；全部失败才让轮询进入失败分支。
    """

    providers: tuple[ActiveAlertProvider, ...]

    async def list_active_alerts(self) -> list[ActiveAlert]:
        results: list[ActiveAlert] = []
        successful_sources = 0
        for provider in self.providers:
            try:
                results.extend(await provider.list_active_alerts())
            except AlertProviderError:
                # 单源故障隔离：继续采集其它 source，不让一个占位配置拖垮全部告警。
                continue
            successful_sources += 1
        if successful_sources == 0:
            raise AlertProviderError("The configured alert provider is unavailable.")
        # 稳定排序保证相同告警集每次生成同样的快照，减少无意义的 SSE 变更。
        return sorted(results, key=lambda alert: (alert.source, alert.starts_at, alert.id))


def build_alertmanager_alert_provider(
    *,
    config_path: Path | str | None = None,
) -> ActiveAlertProvider:
    """从项目配置构建真实的告警读取器。

    每个 source 独立校验：模板里的空占位源或单个畸形条目只会被跳过，
    不会让其它有效源一起失效；只有全部 source 都不可用时才判定配置无效。
    """
    try:
        config = project_config_section("prometheusAlerts", config_path=config_path)
        timeout_seconds = required_float(config, "timeoutSeconds")
        sources = config.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ProjectConfigurationError("At least one alert source must be configured.")
        configured_sources = cast(list[object], sources)
    except ProjectConfigurationError as exc:
        raise AlertProviderError("The configured alert provider is invalid.") from exc
    providers: list[ActiveAlertProvider] = []
    for source in configured_sources:
        try:
            providers.append(_build_alert_provider(source, timeout_seconds=timeout_seconds))
        except ProjectConfigurationError as exc:
            # 只记录安全标签和校验原因，不记录 URL 或凭据。
            logger.warning("Skipping invalid alert source %s: %s", _source_label(source), exc)
    if not providers:
        raise AlertProviderError("The configured alert provider is invalid.")
    return AggregatedAlertProvider(providers=tuple(providers))


def _source_label(source: object) -> str:
    if isinstance(source, Mapping):
        candidate = cast(Mapping[str, object], source).get("id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return "<unknown>"


def _build_alert_provider(source: object, *, timeout_seconds: float) -> ActiveAlertProvider:
    """按 type 构建单个告警 provider；未知类型视为配置错误。"""
    if not isinstance(source, Mapping):
        raise ProjectConfigurationError("Alert source must be an object.")
    source_mapping = cast(Mapping[str, object], source)
    source_id = required_str(source_mapping, "id")
    source_type = required_str(source_mapping, "type")
    alerts_api = required_str(source_mapping, "alertsApi")
    username = _optional_str(source_mapping, "username")
    password = _optional_str(source_mapping, "password")
    # 用户名和密码必须成对出现，避免半配置状态退化成匿名请求。
    if (username is None) != (password is None):
        raise ProjectConfigurationError(
            "Alert source credentials must include username and password."
        )
    if source_type == "alertmanager-v2":
        return AlertmanagerAlertProvider(
            alerts_api=alerts_api,
            timeout_seconds=timeout_seconds,
            source_id=source_id,
            username=username,
            password=password,
        )
    if source_type == "prometheus-v1":
        return PrometheusAlertProvider(
            alerts_api=alerts_api,
            timeout_seconds=timeout_seconds,
            source_id=source_id,
            username=username,
            password=password,
        )
    raise ProjectConfigurationError(f"Unsupported alert source type: {source_type}")


async def _read_json(
    *,
    alerts_api: str,
    timeout_seconds: float,
    username: str | None,
    password: str | None,
    transport: httpx.AsyncBaseTransport | None,
) -> object:
    """GET 告警端点并解析 JSON；网络/解析错误统一转成安全异常。

    不把上游响应体或 URL 写进错误消息，避免泄露内网地址和凭据。
    """
    # BasicAuth 只在两个凭据都存在时启用，与配置校验保持一致。
    auth = (
        httpx.BasicAuth(username, password)
        if username is not None and password is not None
        else None
    )
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            auth=auth,
        ) as client:
            response = await client.get(alerts_api)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AlertProviderError("The configured alert provider is unavailable.") from exc


def _normalized_alerts(
    raw_alerts: list[object],
    *,
    source_id: str,
    source_type: str,
) -> list[ActiveAlert]:
    """归一化整个告警数组；任一条目不是对象则判定响应整体非法。"""
    alerts: list[ActiveAlert] = []
    for item in raw_alerts:
        if not isinstance(item, dict):
            raise AlertProviderError("The configured alert provider returned an invalid response.")
        alert = _normalize_alert(
            cast(dict[str, object], item), source_id=source_id, source_type=source_type
        )
        if alert is not None:
            alerts.append(alert)
    return alerts


def _normalize_alert(
    raw_alert: Mapping[str, object],
    *,
    source_id: str,
    source_type: str,
) -> ActiveAlert | None:
    """把单条厂商告警归一化成 ActiveAlert；非活跃状态返回 None。

    Alertmanager 把状态放在 status.state，Prometheus 也可能放在顶层 state，
    因此两处都读；只保留 active/firing。
    """
    status = _string_mapping(raw_alert.get("status"))
    state = status.get("state", _string_value(raw_alert.get("state"), ""))
    if state not in {"active", "firing"}:
        return None

    labels = _string_mapping(raw_alert.get("labels"))
    annotations = _string_mapping(raw_alert.get("annotations"))
    alert_name = labels.get("alertname", "Unknown alert")
    service = labels.get("service", labels.get("job", "Unspecified service"))
    severity = labels.get("severity", "unknown")
    starts_at = _string_value(raw_alert.get("startsAt"), "") or _string_value(
        raw_alert.get("activeAt"), ""
    )
    fingerprint = _string_value(raw_alert.get("fingerprint"), "")
    # 优先使用厂商 fingerprint；缺失时用稳定复合键，保证跨轮询能识别同一告警。
    alert_id = fingerprint or f"{source_id}:{alert_name}:{service}:{starts_at}"
    summary = annotations.get("summary", annotations.get("description", "No summary provided."))
    # 原始 payload 保留下来供诊断取证，但只存在于快照/任务内，不写结构化日志。
    context = dict(raw_alert)
    context["alertSource"] = source_id
    context["alertSourceType"] = source_type

    return ActiveAlert(
        id=alert_id,
        source=source_id,
        alert_name=alert_name,
        service=service,
        severity=severity,
        status="active",
        starts_at=starts_at,
        summary=summary,
        labels=labels,
        annotations=annotations,
        context=context,
    )


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


def _string_value(value: object, fallback: str) -> str:
    return value if isinstance(value, str) else fallback


def _optional_str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigurationError(f"Alert source field must be a non-empty string: {key}")
    return value.strip()

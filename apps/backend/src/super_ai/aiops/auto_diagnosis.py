"""监控链路第 1→3 层衔接：告警触发的自动诊断配置与请求构造。

链路位置：_alert_poll_job_handler → 本模块 → create_aiops_diagnostic 入队
上游调用：api/app.py 的 _auto_diagnosis_settings / _start_auto_diagnoses
下游消费：诊断任务 payload、去重窗口、每轮触发上限
设计约束：
- 默认关闭；必须配置 ownerEmail 才能确定诊断归属；
- 告警轮询是进程全局的，但诊断必须落到具体 owner；
- 级别过滤大小写不敏感，默认只自动诊断 critical。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from super_ai.alerts import ActiveAlert
from super_ai.project_config import ProjectConfigurationError, load_project_config

DEFAULT_AUTO_DIAGNOSIS_SEVERITIES: tuple[str, ...] = ("critical",)
DEFAULT_AUTO_DIAGNOSIS_DEDUPE_WINDOW_SECONDS = 900
DEFAULT_AUTO_DIAGNOSIS_MAX_PER_POLL = 3


@dataclass(frozen=True, slots=True)
class AutoDiagnosisSettings:
    """已校验的自动诊断策略：owner、级别过滤、去重窗口、每轮上限。"""

    owner_email: str
    severities: frozenset[str]
    dedupe_window_seconds: int = DEFAULT_AUTO_DIAGNOSIS_DEDUPE_WINDOW_SECONDS
    max_per_poll: int = DEFAULT_AUTO_DIAGNOSIS_MAX_PER_POLL

    def matches(self, alert: ActiveAlert) -> bool:
        """告警级别是否在自动诊断白名单内（大小写与空白不敏感）。"""
        return alert.severity.strip().lower() in self.severities


def load_auto_diagnosis_settings(
    config_path: Path | str | None = None,
) -> AutoDiagnosisSettings | None:
    """读取 aiopsAutoDiagnosis；返回 None 表示功能关闭。

    配置缺失、enabled=false 都静默关闭；enabled=true 但 ownerEmail
    非法时明确报配置错误，避免把诊断归到错误用户。
    """
    config = load_project_config(config_path)
    section = config.get("aiopsAutoDiagnosis")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ProjectConfigurationError("aiopsAutoDiagnosis must be an object.")
    values: Mapping[str, object] = cast(Mapping[str, object], section)
    enabled = values.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProjectConfigurationError("aiopsAutoDiagnosis.enabled must be a boolean.")
    if not enabled:
        return None
    owner_email = values.get("ownerEmail", "")
    if not isinstance(owner_email, str) or "@" not in owner_email:
        raise ProjectConfigurationError(
            "aiopsAutoDiagnosis.ownerEmail must identify the diagnosing user."
        )
    return AutoDiagnosisSettings(
        owner_email=owner_email.strip().lower(),
        severities=_severities(values.get("severities")),
        dedupe_window_seconds=_positive_int(
            values.get("dedupeWindowSeconds"),
            DEFAULT_AUTO_DIAGNOSIS_DEDUPE_WINDOW_SECONDS,
            "dedupeWindowSeconds",
        ),
        max_per_poll=_positive_int(
            values.get("maxPerPoll"),
            DEFAULT_AUTO_DIAGNOSIS_MAX_PER_POLL,
            "maxPerPoll",
        ),
    )


def auto_diagnosis_query(alert: ActiveAlert) -> str:
    """构造与手工排查一致的分析师风格查询文本。"""
    parts = [f"排查活跃告警：{alert.alert_name}"]
    if alert.service:
        parts.append(f"服务：{alert.service}")
    parts.append(f"级别：{alert.severity}")
    summary = alert.summary.strip().rstrip("。.!?！？")
    if summary:
        parts.append(f"摘要：{summary}")
    return "，".join(parts) + "。"


def auto_diagnosis_input_payload(alert: ActiveAlert) -> dict[str, object]:
    """构造诊断输入，保留告警 provenance，并标记 autoDiagnosis。

    owner 不在 payload 里由客户端决定；创建任务时会使用已认证上下文。
    """
    return {
        "query": auto_diagnosis_query(alert),
        "alert": {
            **alert.context,
            "alertSource": alert.source,
            "alertName": alert.alert_name,
            "service": alert.service,
            "severity": alert.severity,
            "status": alert.status,
            "startsAt": alert.starts_at,
            "summary": alert.summary,
        },
        "scope": {},
        "alertId": alert.id,
        "autoDiagnosis": True,
    }


def _severities(value: object) -> frozenset[str]:
    """解析级别列表；缺失用默认 critical，空列表/非法元素直接报错。"""
    if value is None:
        return frozenset(DEFAULT_AUTO_DIAGNOSIS_SEVERITIES)
    if not isinstance(value, list) or not value:
        raise ProjectConfigurationError(
            "aiopsAutoDiagnosis.severities must be a non-empty list of severities."
        )
    severities: set[str] = set()
    for item in cast(list[object], value):
        if not isinstance(item, str) or not item.strip():
            raise ProjectConfigurationError(
                "aiopsAutoDiagnosis.severities must be a non-empty list of severities."
            )
        severities.add(item.strip().lower())
    return frozenset(severities)


def _positive_int(value: object, default: int, field: str) -> int:
    """可选的严格正整数配置；缺失用默认值，非法值报配置错误。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProjectConfigurationError(f"aiopsAutoDiagnosis.{field} must be a positive integer.")
    return value

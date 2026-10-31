"""监控链路第 1 层：按配置选择日志 adapter。

链路位置：_aiops_diagnostic_runner → build_log_store → ClsLogStore / FileLogStore
上游调用：api/app.py 构建诊断 runner 时
下游消费：AiopsDiagnosticService 的 SearchLog 工具
设计约束：
- 没有 logStore 配置时保持旧行为，默认 CLS；
- 未知 type/format 直接报配置错误，不静默降级；
- 本地文件模式的 maxBytes/maxRecords 必须是正整数。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from super_ai.log_store.cls_store import ClsLogStore
from super_ai.log_store.file_store import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_RECORDS,
    SUPPORTED_LOG_FORMATS,
    FileLogStore,
)
from super_ai.log_store.protocol import LogStore
from super_ai.mcp_client import LocalMcpClient
from super_ai.mcp_connections import McpConnectionService
from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_str,
)


def build_log_store(
    *,
    config_path: Path | str | None = None,
    mcp_client: LocalMcpClient | None = None,
    mcp_client_provider: McpConnectionService | None = None,
) -> LogStore:
    """构建配置指定的日志 adapter；缺少 logStore 段时回退 CLS。"""
    try:
        cfg = project_config_section("logStore", config_path=config_path)
    except ProjectConfigurationError:
        # 向后兼容：旧配置没有 logStore 段，仍按 CLS 运行。
        cfg = {"type": "cls"}
    store_type = str(cfg.get("type") or "cls")
    if store_type == "file":
        log_format = str(cfg.get("format") or "auto")
        if log_format not in SUPPORTED_LOG_FORMATS:
            raise ProjectConfigurationError(
                f"Unsupported logStore format: {log_format}"
            )
        return FileLogStore(
            file_path=Path(required_str(cfg, "filePath")),
            log_format=log_format,
            max_bytes=_optional_positive_int(cfg, "maxBytes", DEFAULT_MAX_BYTES),
            max_records=_optional_positive_int(cfg, "maxRecords", DEFAULT_MAX_RECORDS),
        )
    if store_type != "cls":
        raise ProjectConfigurationError(f"Unsupported logStore type: {store_type}")
    # CLS 复用 clsLogUpload 的 region/topic，保持与日志上传配置一致。
    cls_cfg = project_config_section("clsLogUpload", config_path=config_path)
    return ClsLogStore(
        region=required_str(cls_cfg, "region"),
        topic_id=required_str(cls_cfg, "topicId"),
        mcp_client=mcp_client,
        mcp_client_provider=mcp_client_provider,
    )


def _optional_positive_int(cfg: Mapping[str, Any], key: str, default: int) -> int:
    """可选的严格正整数；缺失用默认值，非法值直接报配置错误。"""
    value = cfg.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectConfigurationError(
            f"logStore field must be a positive integer: {key}"
        )
    return value

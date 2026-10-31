"""监控链路第 1 层：日志源适配边界（LogStore Protocol）。

链路位置：Planner/Executor → LogStore → CLS MCP / 本地文件
上游调用：AiopsDiagnosticService.build_scoped_steps / _run_one
下游消费：log 类型诊断证据 → 报告引用 → 前端证据链
设计约束：
- 上层只认识 service/incidentId/traceId/level/text/from/to/limit；
- 每个 adapter 必须自行保证 owner 作用域与字段脱敏；
- recordCount 是返回条数，excludedRecordCount 是被过滤/丢弃的条数。
"""

from __future__ import annotations

from typing import Protocol, TypedDict

from super_ai.memory.repositories import JsonDict


class LogSearchResult(TypedDict):
    """一次日志查询的统一结果形状，记录已脱敏且落在任务范围内。"""

    records: list[JsonDict]
    recordCount: int
    excludedRecordCount: int


class LogStore(Protocol):
    """日志源协议：先构建已作用域参数，再执行查询。"""

    tool_name: str

    def build_args(self, step: JsonDict, scope: JsonDict) -> JsonDict:
        """把 planner 的中性参数翻译成 adapter 原生参数。

        planner 只输出 service/incidentId/traceId/level/text/from/to/limit；
        CLS 渲染成 CQL Query，本地文件保持结构化字段。旧 Query 仍兼容解析。
        """
        ...

    async def search(
        self, *, step: JsonDict, scope: JsonDict, owner_user_id: str
    ) -> LogSearchResult:
        """执行查询，返回已脱敏、已按 scope 过滤的记录。

        owner_user_id 用于选择该用户的 MCP 连接，不能由客户端直接提供。
        """
        ...

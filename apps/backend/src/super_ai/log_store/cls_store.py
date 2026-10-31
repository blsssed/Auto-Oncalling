"""监控链路第 1 层：腾讯云 CLS 日志 adapter。

链路位置：LogQuery → ClsLogStore → MCP SearchLog → scoped_records
上游调用：AiopsDiagnosticService._run_one（tool=SearchLog）
下游消费：log 类型证据；结果已经过 scope 过滤、字段白名单和脱敏
设计约束：
- 必须使用按 owner 解析出的 MCP 连接，不能共享全局凭据；
- step 参数在上游已完成作用域处理，这里不能再次 Query 编码；
- 返回记录数只统计过滤后的记录，另报 excludedRecordCount。
"""

from __future__ import annotations

from typing import cast

from super_ai.aiops.investigation import scoped_records, scoped_step
from super_ai.log_store.protocol import LogSearchResult
from super_ai.mcp_client import LocalMcpClient, McpClientError
from super_ai.mcp_connections import McpConnectionService
from super_ai.memory.repositories import JsonDict


class ClsLogStore:
    """通过运行时发现的 SearchLog MCP 工具查询 CLS。"""

    tool_name = "SearchLog"

    def __init__(
        self,
        *,
        region: str,
        topic_id: str,
        mcp_client: LocalMcpClient | None = None,
        mcp_client_provider: McpConnectionService | None = None,
    ) -> None:
        """注入固定客户端或按用户解析的客户端提供者，二者至少一个。"""
        if mcp_client is None and mcp_client_provider is None:
            raise ValueError("An MCP client or provider is required.")
        self._region = region
        self._topic_id = topic_id
        self._mcp_client = mcp_client
        self._mcp_client_provider = mcp_client_provider

    async def _client_for(self, owner_user_id: str) -> LocalMcpClient:
        """按 owner 解析 MCP 客户端；provider 优先于固定客户端。

        这是用户凭据隔离边界：不同用户的 CLS 连接不能混用。
        """
        if self._mcp_client_provider is not None:
            return await self._mcp_client_provider.client_for_user(owner_user_id=owner_user_id)
        if self._mcp_client is None:
            raise McpClientError("MCP client is unavailable.")
        return self._mcp_client

    def build_args(self, step: JsonDict, scope: JsonDict) -> JsonDict:
        """复用 investigation.scoped_step 生成已钳制的 CLS SearchLog 参数。"""
        return scoped_step(step, scope, self._region, self._topic_id)

    async def search(
        self, *, step: JsonDict, scope: JsonDict, owner_user_id: str
    ) -> LogSearchResult:
        """调用真实 MCP SearchLog，并对返回记录做二次 scope 过滤与脱敏。"""
        raw = step.get("arguments")
        arguments = cast(JsonDict, raw) if isinstance(raw, dict) else {}
        client = await self._client_for(owner_user_id)
        # 这里直接使用已作用域的 arguments，不再经过 LogQuery，避免 Query 双重编码。
        output = await client.call_tool(self.tool_name, arguments)
        records, rejected = scoped_records(output, scope)
        return {
            "records": records,
            "recordCount": len(records),
            # rejected 包含 scope 外、字段非法或被脱敏规则剔除的记录。
            "excludedRecordCount": rejected,
        }

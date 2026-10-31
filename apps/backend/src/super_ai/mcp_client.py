"""MCP 客户端边界：只调用用户启用的真实连接与真实工具。

阅读顺序：call_tool → discover_tools → _run_connection → _run_sse/_run_streamable_http。
call_tool 只看三处：怎么选连接、结果怎么提取、失败怎么审计。
第一次读请跳过：传输细节、超时/重试参数、create_current_time_tool。

不变量：
- 不提供 mock 日志兜底，MCP 不可用就是失败证据；
- 日志只记录工具名、参数 key、结果条数与耗时，不记录参数值/正文/凭据；
- 多连接时先发现工具再定位唯一 server，同名或缺失都明确失败。

【学习路线 · 监控链路支撑层】链路定位：第 2 站 _executor 的真实工具
边界，CLS 日志经此调用，无 mock 兜底。重点函数：LocalMcpClient.call_tool、
discover_tools。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, cast

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from super_ai.observability import elapsed_ms, emit_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str = "default"


@dataclass(frozen=True, slots=True)
class McpServerConnection:
    name: str
    url: str
    transport: str = "sse"
    timeout_seconds: float = 15
    retries: int = 1


class McpClientError(RuntimeError):
    """MCP 连接、工具发现或工具调用失败的统一异常；调用方据此记为失败证据。"""


def create_current_time_tool() -> Any:
    """Create the explicit time tool used before time-range MCP queries."""
    from langchain_core.tools import StructuredTool

    def get_current_time() -> dict[str, object]:
        now = datetime.now(timezone.utc)
        return {"iso8601": now.isoformat(), "unixMilliseconds": int(now.timestamp() * 1000)}

    return StructuredTool.from_function(
        func=get_current_time,
        name="get_current_time",
        description="Return the current UTC time and Unix timestamp in milliseconds.",
    )


class LocalMcpClient:
    def __init__(
        self,
        endpoint: str | None = None,
        *,
        timeout_seconds: float = 15,
        retries: int = 1,
        connections: Sequence[McpServerConnection] | None = None,
    ) -> None:
        configured = list(connections or [])
        if not configured and endpoint is not None:
            configured = [
                McpServerConnection(
                    name="cls",
                    url=endpoint,
                    transport="sse",
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                )
            ]
        self._connections = tuple(configured)

    async def get_langchain_tools(self) -> list[Any]:
        await self.discover_tools()
        client = MultiServerMCPClient(
            cast(
                Any,
                {
                    connection.name: {
                        "transport": (
                            "http" if connection.transport == "streamable_http" else "sse"
                        ),
                        "url": connection.url,
                    }
                    for connection in self._connections
                },
            ),
            handle_tool_errors=False,
        )
        return await client.get_tools()

    async def discover_tools(self) -> list[McpToolDefinition]:
        definitions: list[McpToolDefinition] = []
        seen: set[str] = set()
        for connection in self._connections:
            result = await self._run_connection(
                connection,
                lambda session: session.list_tools(),
            )
            for tool in result.tools:
                if tool.name in seen:
                    raise McpClientError(f"Duplicate MCP tool name: {tool.name}")
                seen.add(tool.name)
                definitions.append(
                    McpToolDefinition(
                        tool.name,
                        tool.description or "MCP tool",
                        tool.inputSchema,
                        connection.name,
                    )
                )
        return definitions

    async def readiness(self) -> dict[str, object]:
        """探测 MCP 是否可用并返回工具数量；失败时返回 ok=False 而不是抛异常。"""
        try:
            tools = await self.discover_tools()
        except McpClientError as exc:
            return {
                "ok": False,
                "endpoint": self._connections[0].url if self._connections else None,
                "toolCount": 0,
                "error": str(exc),
            }
        return {
            "ok": True,
            "endpoint": self._connections[0].url if self._connections else None,
            "toolCount": len(tools),
            "error": None,
        }

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """调用真实 MCP 工具，并在 started/completed/failed 三个节点写审计事件。

        日志只包含工具名、参数 key、结果条数与耗时；参数值、输出正文和凭据不落日志。
        """
        started_at = monotonic()
        # 只记录参数 key 的排序结果，避免把查询内容或凭据写进日志。
        emit_event(logger, "mcp.tool.started", toolName=name, argumentKeys=sorted(arguments))
        try:
            if len(self._connections) == 1:
                connection = self._connections[0]
                result = await self._run(
                    lambda session: session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=timedelta(
                            seconds=connection.timeout_seconds
                        ),
                    )
                )
            else:
                # 多连接时先发现工具再定位唯一 server；同名或缺失都明确失败，避免误调。
                matching = [tool for tool in await self.discover_tools() if tool.name == name]
                if len(matching) != 1:
                    raise McpClientError(f"MCP tool is unavailable or ambiguous: {name}")
                connection = next(
                    item for item in self._connections if item.name == matching[0].server_name
                )
                result = await self._run_connection(
                    connection,
                    lambda session: session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=timedelta(
                            seconds=connection.timeout_seconds
                        ),
                    ),
                )
        except Exception as exc:
            emit_event(
                logger,
                "mcp.tool.failed",
                toolName=name,
                errorCategory=exc.__class__.__name__,
                durationMs=elapsed_ms(started_at),
            )
            raise
        # 工具返回 isError 视为失败，不把错误正文当作正常结果交给诊断链路。
        if result.isError:
            emit_event(
                logger,
                "mcp.tool.failed",
                toolName=name,
                errorCategory="McpToolError",
                durationMs=elapsed_ms(started_at),
            )
            raise McpClientError(f"MCP tool {name} returned an error")
        # 只提取 type/text 两个字段，不解析或记录完整的 MCP 响应结构。
        payload = [
            {"type": item.type, "text": getattr(item, "text", None)} for item in result.content
        ]
        emit_event(
            logger,
            "mcp.tool.completed",
            toolName=name,
            resultItemCount=len(payload),
            durationMs=elapsed_ms(started_at),
        )
        return payload

    async def _run(self, operation: Callable[[Any], Awaitable[Any]]) -> Any:
        if len(self._connections) != 1:
            raise McpClientError("A single MCP connection is required for this operation.")
        return await self._run_connection(self._connections[0], operation)

    async def _run_connection(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """按配置重试次数尝试单个连接；全部失败后抛出统一的 McpClientError。"""
        error: Exception | None = None
        # 第 n 次失败后等待 0.2*n 秒再重试；最终错误只保留连接 url，不带响应正文。
        for attempt in range(connection.retries + 1):
            try:
                if connection.transport == "streamable_http":
                    return await self._run_streamable_http(connection, operation)
                return await self._run_sse(connection, operation)
            except Exception as exc:
                error = exc
                if attempt < connection.retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise McpClientError(f"MCP server unavailable at {connection.url}") from error

    async def _run_sse(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        async with sse_client(
            connection.url,
            timeout=connection.timeout_seconds,
            sse_read_timeout=connection.timeout_seconds,
        ) as streams:
            return await _run_initialized_session(
                streams[0],
                streams[1],
                operation,
                connection.timeout_seconds,
            )

    async def _run_streamable_http(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        async with httpx.AsyncClient(timeout=connection.timeout_seconds) as http_client:
            async with streamable_http_client(
                connection.url,
                http_client=http_client,
            ) as streams:
                return await _run_initialized_session(
                    streams[0],
                    streams[1],
                    operation,
                    connection.timeout_seconds,
                )


async def _run_initialized_session(
    read_stream: Any,
    write_stream: Any,
    operation: Callable[[Any], Awaitable[Any]],
    timeout_seconds: float,
) -> Any:
    """初始化 MCP 会话，并用 asyncio.wait_for 给单次操作加上硬超时。"""
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        return await asyncio.wait_for(operation(session), timeout=timeout_seconds)

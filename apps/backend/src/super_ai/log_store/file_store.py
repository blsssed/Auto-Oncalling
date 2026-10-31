"""监控链路第 1 层：本地文件日志 adapter（有界尾部读取）。

链路位置：LogQuery → FileLogStore → 本地 JSONL/JSON 数组 → scoped_records
上游调用：build_log_store(type="file")、离线诊断/演示
下游消费：log 类型证据；与 CLS 共享同一套 scope 过滤和字段白名单
设计约束：
- 这是“有界尾部读取”，不是通用日志引擎；不建索引、不递归扫描；
- maxBytes 与 maxRecords 是硬限制，坏行只计数不抛错；
- 目录/glob 只读取配置路径内匹配到的受支持文件。
"""

from __future__ import annotations

import glob
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from super_ai.aiops.investigation import scoped_records
from super_ai.log_store.protocol import LogSearchResult
from super_ai.log_store.query import LogQuery
from super_ai.memory.repositories import JsonDict

SUPPORTED_LOG_FORMATS = frozenset({"auto", "jsonl", "json-array"})
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_RECORDS = 20_000
_DIRECTORY_PATTERNS = ("*.jsonl", "*.ndjson", "*.json", "*.log", "*.log.*")


class FileLogStore:
    """读取本地 JSONL 或 JSON 数组日志，并对读取量设硬上限。"""

    tool_name = "SearchLog"

    def __init__(
        self,
        *,
        file_path: Path,
        log_format: str = "auto",
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        """校验格式与上限；bool 不算合法整数，避免 True 被当成 1 通过。"""
        if log_format not in SUPPORTED_LOG_FORMATS:
            raise ValueError(f"Unsupported local log format: {log_format}")
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer.")
        if isinstance(max_records, bool) or max_records <= 0:
            raise ValueError("max_records must be a positive integer.")
        self._file_path = file_path
        self._format = log_format
        self._max_bytes = max_bytes
        self._max_records = max_records

    def build_args(self, step: JsonDict, scope: JsonDict) -> JsonDict:
        """构建结构化参数（不是 CLS 参数），并保留步骤 id/purpose 供 SSE 展示。"""
        query = LogQuery.from_step(step, scope)
        return {
            "id": str(step.get("id") or "search-file-logs"),
            "tool": self.tool_name,
            "purpose": str(step.get("purpose") or "获取当前事故范围内的日志证据"),
            "arguments": query.to_arguments(),
        }

    async def search(
        self, *, step: JsonDict, scope: JsonDict, owner_user_id: str
    ) -> LogSearchResult:
        """读取文件 → 归一化时间 → scope 过滤 → 查询匹配 → 截断 limit。"""
        # 本地文件没有 owner 隔离语义；保留参数是为了满足 LogStore 协议。
        del owner_user_id
        query = LogQuery.from_step(step, scope)
        records: list[JsonDict] = []
        malformed = 0
        for path in _resolve_files(self._file_path):
            file_records, file_malformed = _read_file(
                path,
                log_format=self._format,
                max_bytes=self._max_bytes,
                remaining=self._max_records - len(records),
            )
            malformed += file_malformed
            records.extend(_normalize_record(record) for record in file_records)
            if len(records) >= self._max_records:
                break
        output = [
            {
                "type": "text",
                "text": json.dumps(
                    [{"LogJson": json.dumps(record, ensure_ascii=False)} for record in records],
                    ensure_ascii=False,
                ),
            }
        ]
        scoped, rejected = scoped_records(output, scope)
        matching = [record for record in scoped if query.matches(record)]
        query_rejected = len(scoped) - len(matching)
        # limit 只限制最终返回条数；excluded 仍如实反映被排除的总量。
        selected = matching[: query.limit]
        return {
            "records": selected,
            "recordCount": len(selected),
            "excludedRecordCount": rejected + malformed + query_rejected,
        }


def _resolve_files(file_path: Path) -> list[Path]:
    """按“目录 → glob → 单文件”的优先级解析路径。

    目录只匹配受支持的日志后缀，避免把任意文件带进诊断。
    """
    if file_path.is_dir():
        files: set[Path] = set()
        for pattern in _DIRECTORY_PATTERNS:
            files.update(path for path in file_path.glob(pattern) if path.is_file())
        return _newest_first(files)
    raw_path = str(file_path)
    if any(character in raw_path for character in "*?["):
        matches = [Path(item) for item in glob.glob(raw_path, recursive=True)]
        return _newest_first(path for path in matches if path.is_file())
    if not file_path.is_file():
        raise FileNotFoundError(f"Log file does not exist: {file_path}")
    return [file_path]


def _newest_first(paths: Iterable[Path]) -> list[Path]:
    """按 mtime 倒序、文件名升序排列，优先读取最新轮转文件。"""
    return sorted(
        paths,
        key=lambda path: (-path.stat().st_mtime, path.name),
    )


def _read_file(
    path: Path,
    *,
    log_format: str,
    max_bytes: int,
    remaining: int,
) -> tuple[list[JsonDict], int]:
    """按解析出的格式读取一个文件，返回记录与坏行计数。"""
    if remaining <= 0:
        return [], 0
    size = path.stat().st_size
    resolved_format = _resolved_format(path, log_format)
    if resolved_format == "json-array":
        # JSON 数组必须整体解析，无法做尾部截断；超限时明确提示改用 JSONL。
        if size > max_bytes:
            raise ValueError(
                f"Log file exceeds maxBytes and must be JSONL: {path}"
            )
        return _read_json_array(path, remaining)
    return _read_jsonl(path, max_bytes=max_bytes, remaining=remaining)


def _resolved_format(path: Path, log_format: str) -> str:
    """确定文件格式：显式配置优先，其次看后缀，最后嗅探前 4 KiB。"""
    if log_format != "auto":
        return log_format
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    if suffix == ".json":
        return "json-array"
    with path.open("rb") as handle:
        head = handle.read(4096)
    stripped = head.lstrip()
    return "json-array" if stripped.startswith(b"[") else "jsonl"


def _read_json_array(path: Path, remaining: int) -> tuple[list[JsonDict], int]:
    """解析整个 JSON 数组；非对象元素计入坏行，达到 remaining 即停止。"""
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"Log file must contain a JSON array: {path}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"Log file must contain a JSON array: {path}")
    records: list[JsonDict] = []
    malformed = 0
    for item in cast(list[object], parsed):
        if not isinstance(item, dict):
            malformed += 1
            continue
        if len(records) >= remaining:
            break
        records.append(cast(JsonDict, item))
    return records, malformed


def _read_jsonl(
    path: Path, *, max_bytes: int, remaining: int
) -> tuple[list[JsonDict], int]:
    """从文件末尾读取最多 max_bytes，按行解析 JSONL。

    尾部起点可能落在一条记录中间，因此先检查 offset-1 是否为换行；
    不是换行就丢弃第一行，避免把半条 JSON 当成坏数据。
    """
    size = path.stat().st_size
    offset = max(0, size - max_bytes)
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
        if offset > 0:
            handle.seek(offset - 1)
            starts_at_boundary = handle.read(1) in {b"\n", b"\r"}
        else:
            starts_at_boundary = True
    lines = data.decode("utf-8", errors="replace").splitlines()
    if offset > 0 and not starts_at_boundary and lines:
        # 尾部读取从记录中间开始时，首行必然不完整，直接丢弃。
        lines = lines[1:]
    records: list[JsonDict] = []
    malformed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed: object = json.loads(stripped)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(parsed, dict):
            malformed += 1
            continue
        if len(records) >= remaining:
            break
        records.append(cast(JsonDict, parsed))
    return records, malformed


def _normalize_record(record: JsonDict) -> JsonDict:
    """把常见 time 字段归一化为 timestamp，保留原始字段不动。"""
    normalized = dict(record)
    if "timestamp" not in normalized and "time" in normalized:
        timestamp = _normalize_timestamp(normalized["time"])
        if timestamp is not None:
            normalized["timestamp"] = timestamp
    return normalized


def _normalize_timestamp(value: object) -> str | None:
    """把 epoch 秒/毫秒或数字字符串转成 UTC ISO 时间；无法识别返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return value
    else:
        return None
    if numeric <= 0:
        return None
    # 13 位左右视为毫秒；10 位左右保留为秒，避免把 2026 年解析成 1970 年。
    seconds = numeric / 1000 if numeric >= 1_000_000_000_000 else numeric
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None

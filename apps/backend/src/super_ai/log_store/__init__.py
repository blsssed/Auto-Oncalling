"""LogStore abstraction for AIOps log evidence sources."""

from super_ai.log_store.cls_store import ClsLogStore
from super_ai.log_store.factory import build_log_store
from super_ai.log_store.file_store import FileLogStore
from super_ai.log_store.protocol import LogSearchResult, LogStore
from super_ai.log_store.query import LogQuery, parse_legacy_query

__all__ = [
    "ClsLogStore",
    "FileLogStore",
    "LogQuery",
    "LogSearchResult",
    "LogStore",
    "build_log_store",
    "parse_legacy_query",
]

"""Database configuration and session helpers for memory persistence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_str,
)

DEFAULT_MEMORY_DATABASE_URL = "sqlite+aiosqlite:///./var/memory.sqlite3"


@dataclass(frozen=True, slots=True)
class MemoryDatabaseSettings:
    """Runtime database settings for memory persistence."""

    database_url: str = DEFAULT_MEMORY_DATABASE_URL


def load_memory_database_settings(config_path: Path | str | None = None) -> MemoryDatabaseSettings:
    """Load memory database settings from the repository project config."""
    try:
        backend_config = project_config_section("backend", config_path=config_path)
        database_url = required_str(backend_config, "memoryDatabaseUrl")
    except ProjectConfigurationError as exc:
        raise RuntimeError(str(exc)) from exc
    return MemoryDatabaseSettings(database_url=database_url)


def create_memory_engine(
    database_url: str | None = None,
    *,
    echo: bool = False,
    config_path: Path | str | None = None,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine for memory persistence."""
    settings = load_memory_database_settings(config_path) if database_url is None else None
    resolved_url = settings.database_url if settings is not None else database_url
    if resolved_url is None:
        resolved_url = DEFAULT_MEMORY_DATABASE_URL
    engine = create_async_engine(resolved_url, echo=echo)
    _apply_sqlite_pragmas(engine)
    return engine


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Enable WAL, busy timeout and NORMAL sync on every SQLite connection.

    后台任务与 HTTP 请求会并发读写同一个 SQLite 文件；没有 WAL/busy_timeout
    时任何并发写入都会以 `database is locked` 变成无关功能的 500。
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:  # pyright: ignore[reportUnusedFunction]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def create_memory_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory for repository implementations."""
    return async_sessionmaker(engine, expire_on_commit=False)

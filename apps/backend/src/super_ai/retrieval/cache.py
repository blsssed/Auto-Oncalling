"""Short-lived in-process cache for knowledge retrieval results.

The cache is intentionally small and time-bounded: retrieval results are
derived from mutable knowledge bases, so entries expire quickly instead of
requiring every indexing path to publish an invalidation event.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, cast

from super_ai.project_config import ProjectConfigurationError, load_project_config

if TYPE_CHECKING:
    from super_ai.retrieval.tool import KnowledgeRetrievalToolResult

DEFAULT_RETRIEVAL_CACHE_TTL_SECONDS = 30.0
DEFAULT_RETRIEVAL_CACHE_MAX_ENTRIES = 128


@dataclass(frozen=True)
class RetrievalCacheStats:
    hits: int
    misses: int
    size: int


class RetrievalCache:
    """Bounded TTL cache keyed by the full retrieval request scope."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_RETRIEVAL_CACHE_TTL_SECONDS,
        max_entries: int = DEFAULT_RETRIEVAL_CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Retrieval cache ttl_seconds must be positive.")
        if max_entries < 1:
            raise ValueError("Retrieval cache max_entries must be at least 1.")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, KnowledgeRetrievalToolResult]] = (
            OrderedDict()
        )
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> KnowledgeRetrievalToolResult | None:
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            self._misses += 1
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return value

    def put(self, key: str, value: KnowledgeRetrievalToolResult) -> None:
        self._entries[key] = (self._clock() + self._ttl_seconds, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def invalidate(self) -> None:
        self._entries.clear()

    def stats(self) -> RetrievalCacheStats:
        return RetrievalCacheStats(hits=self._hits, misses=self._misses, size=len(self._entries))


def build_retrieval_cache(config_path: Path | str | None = None) -> RetrievalCache | None:
    """Build the configured retrieval cache; a missing section uses bounded defaults.

    ``retrievalCache.enabled=false`` disables caching entirely. Entries always expire
    after ``ttlSeconds`` so indexing changes become visible without explicit invalidation.
    """
    raw = load_project_config(config_path)
    section = raw.get("retrievalCache")
    if section is None:
        return RetrievalCache()
    if not isinstance(section, Mapping):
        raise ProjectConfigurationError("retrievalCache must be an object.")
    values: Mapping[str, object] = cast(Mapping[str, object], section)
    enabled = values.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ProjectConfigurationError("retrievalCache.enabled must be a boolean.")
    if not enabled:
        return None
    ttl_value = values.get("ttlSeconds", DEFAULT_RETRIEVAL_CACHE_TTL_SECONDS)
    if isinstance(ttl_value, bool) or not isinstance(ttl_value, (int, float)) or ttl_value <= 0:
        raise ProjectConfigurationError("retrievalCache.ttlSeconds must be a positive number.")
    max_entries = values.get("maxEntries", DEFAULT_RETRIEVAL_CACHE_MAX_ENTRIES)
    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
        raise ProjectConfigurationError("retrievalCache.maxEntries must be a positive integer.")
    return RetrievalCache(ttl_seconds=float(ttl_value), max_entries=max_entries)

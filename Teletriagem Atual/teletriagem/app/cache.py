"""LRU cache with TTL semantics keyed by xxhash digests."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Optional, Tuple, TypeVar

try:
    import xxhash  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    xxhash = None
    import hashlib

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheEntry(Generic[V]):
    value: V
    expires_at: float
    meta: Optional[dict] = None


class TTLCache(Generic[K, V]):
    """A minimal LRU cache with TTL support suitable for asyncio workloads."""

    def __init__(self, maxsize: int, ttl_seconds: int) -> None:
        self.maxsize = max(1, maxsize)
        self.ttl_seconds = max(1, ttl_seconds)
        self._store: "OrderedDict[K, CacheEntry[V]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def digest(payload: str) -> str:
        if xxhash is not None:
            return xxhash.xxh64_hexdigest(payload)
        return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()

    def _purge(self) -> None:
        now = time.monotonic()
        keys_to_delete = [key for key, entry in self._store.items() if entry.expires_at <= now]
        for key in keys_to_delete:
            self._store.pop(key, None)

    def get(self, key: K) -> Optional[Tuple[V, Optional[dict]]]:
        with self._lock:
            self._purge()
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return entry.value, entry.meta

    def set(self, key: K, value: V, meta: Optional[dict] = None) -> None:
        with self._lock:
            self._purge()
            expires_at = time.monotonic() + self.ttl_seconds
            self._store[key] = CacheEntry(value=value, expires_at=expires_at, meta=meta)
            self._store.move_to_end(key)
            if len(self._store) > self.maxsize:
                self._store.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": self.hits / max(1, self.hits + self.misses),
            }


__all__ = ["TTLCache", "CacheEntry"]

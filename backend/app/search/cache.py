"""In-memory TTL cache for query embeddings and search results."""

import threading
import time
from typing import Any

_DEFAULT_TTL = 3600  # 1 hour


class TTLCache:
    """Thread-safe TTL cache with LRU eviction."""

    def __init__(self, ttl: int = _DEFAULT_TTL, maxsize: int = 500):
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _normalize_key(self, key: str) -> str:
        return key.strip()

    def get(self, key: str) -> Any | None:
        nkey = self._normalize_key(key)
        with self._lock:
            entry = self._store.get(nkey)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[nkey]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        nkey = self._normalize_key(key)
        with self._lock:
            if len(self._store) >= self._maxsize:
                self._evict()
            self._store[nkey] = (time.monotonic(), value)

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._ttl]
        for k in expired:
            del self._store[k]
        if len(self._store) >= self._maxsize:
            oldest = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest]


embedding_cache = TTLCache(ttl=3600, maxsize=500)
hyde_cache = TTLCache(ttl=3600, maxsize=200)

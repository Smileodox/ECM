"""TTL cache with optional Redis backend (falls back to in-memory)."""

import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 3600  # 1 hour


class _InMemoryCache:
    """Thread-safe in-memory TTL cache with LRU eviction."""

    def __init__(self, ttl: int = _DEFAULT_TTL, maxsize: int = 500):
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        nkey = key.strip()
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
        nkey = key.strip()
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


class _RedisCache:
    """Redis-backed TTL cache. Serializes values as JSON."""

    def __init__(self, client: Any, ttl: int = _DEFAULT_TTL, prefix: str = "cache"):
        self._client = client
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key.strip()}"

    def get(self, key: str) -> Any | None:
        try:
            raw = self._client.get(self._key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self._client.setex(self._key(key), self._ttl, json.dumps(value))
        except Exception:
            pass


def _make_cache(ttl: int, maxsize: int, prefix: str) -> _InMemoryCache | _RedisCache:
    from app.config import settings
    if settings.redis_url:
        try:
            import redis
            client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            logger.info("Using Redis cache (%s) for %s", settings.redis_url.split("@")[-1], prefix)
            return _RedisCache(client, ttl=ttl, prefix=prefix)
        except Exception:
            logger.warning("Redis unavailable, falling back to in-memory cache for %s", prefix)
    return _InMemoryCache(ttl=ttl, maxsize=maxsize)


embedding_cache = _make_cache(ttl=3600, maxsize=500, prefix="emb")
hyde_cache = _make_cache(ttl=3600, maxsize=200, prefix="hyde")

import logging

from slowapi import Limiter
from starlette.requests import Request

logger = logging.getLogger(__name__)


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _build_limiter() -> Limiter:
    from app.config import settings
    if settings.redis_url:
        try:
            import redis as _redis
            client = _redis.from_url(settings.redis_url, socket_connect_timeout=2)
            client.ping()
            client.close()
            return Limiter(
                key_func=_get_client_ip,
                default_limits=["100/minute"],
                storage_uri=settings.redis_url,
            )
        except Exception:
            logger.warning("Redis unavailable for rate limiter, using in-memory")
    return Limiter(key_func=_get_client_ip, default_limits=["100/minute"])


limiter = _build_limiter()

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import AsyncGenerator

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncAzureOpenAI, AsyncOpenAI, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    endpoint: str = ""
    key_env: str = ""


@lru_cache(maxsize=1)
def get_available_models() -> tuple[ModelInfo, ...]:
    if not settings.available_models:
        return (ModelInfo(id=settings.azure_openai_deployment, label=settings.azure_openai_deployment),)
    try:
        raw = json.loads(settings.available_models)
        models = []
        for m in raw:
            info = ModelInfo(
                id=m["id"],
                label=m["label"],
                endpoint=m.get("endpoint", ""),
                key_env=m.get("key_env", ""),
            )
            if info.endpoint and info.key_env and not os.environ.get(info.key_env):
                logger.info("Skipping model %s: env var %s not set", info.id, info.key_env)
                continue
            models.append(info)
        return tuple(models) if models else (ModelInfo(id=settings.azure_openai_deployment, label=settings.azure_openai_deployment),)
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Failed to parse AVAILABLE_MODELS, using default")
        return (ModelInfo(id=settings.azure_openai_deployment, label=settings.azure_openai_deployment),)


def resolve_model(model_name: str | None) -> str:
    if not model_name:
        return settings.azure_openai_deployment
    allowed = {m.id for m in get_available_models()}
    if model_name in allowed:
        return model_name
    logger.warning("Requested model %s not in allowed list, using default", model_name)
    return settings.azure_openai_deployment


def _get_model_info(model_id: str) -> ModelInfo | None:
    for m in get_available_models():
        if m.id == model_id:
            return m
    return None


@lru_cache(maxsize=1)
def _azure_openai_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        timeout=httpx.Timeout(60.0, connect=10.0),
    )


_serverless_clients: dict[str, AsyncOpenAI] = {}


def _serverless_client(endpoint: str, key_env: str) -> AsyncOpenAI:
    if endpoint not in _serverless_clients:
        _serverless_clients[endpoint] = AsyncOpenAI(
            api_key=os.environ[key_env],
            base_url=endpoint,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
    return _serverless_clients[endpoint]


async def stream_chat(
    model_id: str,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> AsyncGenerator[str, None]:
    info = _get_model_info(model_id)

    if info and info.endpoint:
        client = _serverless_client(info.endpoint, info.key_env)
    else:
        client = _azure_openai_client()

    # Open the stream with a short bounded retry. Rate-limit (429 / TPM bursts) and
    # transient connection errors occur at request-open, BEFORE any token is yielded,
    # so retrying here is safe and never replays partial output.
    last_exc: Exception | None = None
    stream = None
    for attempt in range(4):  # 1 try + 3 retries
        if attempt:
            await asyncio.sleep((0.5, 1.5, 3.0)[attempt - 1])
        try:
            stream = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                stream=True,
            )
            break
        except (RateLimitError, APIConnectionError, APITimeoutError) as e:
            last_exc = e
            logger.warning("stream_chat open failed (%s), retry %d/3", type(e).__name__, attempt + 1)
    else:
        raise last_exc  # all attempts exhausted

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

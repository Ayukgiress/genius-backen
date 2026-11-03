"""LLM provider abstraction with fallback and per-user rate limiting.

Supports Gemini, Groq, and OpenRouter. Providers are tried in order
(Groq -> Gemini -> OpenRouter) until one succeeds. Per-user rate limits
are enforced via Redis when REDIS_URL is available, with an in-memory
fallback so the service degrades gracefully without Redis.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

LLMMessage = Dict[str, str]

# Default per-user rate limit: requests per minute per user.
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
RATE_LIMIT_WINDOW_SECONDS = 60


class LLMProviderError(Exception):
    """Raised when an LLM provider fails."""


class RateLimitExceeded(LLMProviderError):
    """Raised when a user's per-minute rate limit is exceeded."""


class LLMProvider(ABC):
    """Abstract LLM provider."""

    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model

    @abstractmethod
    async def complete(self, messages: List[LLMMessage], **kwargs: Any) -> str:
        """Return the assistant's text response for the given messages."""


class GroqProvider(LLMProvider):
    """Groq chat completions provider."""

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        super().__init__("groq", model)
        try:
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=api_key)
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise LLMProviderError("groq package not installed") from exc

    async def complete(self, messages: List[LLMMessage], **kwargs: Any) -> str:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4000),
        )
        content = response.choices[0].message.content
        if content is None:
            raise LLMProviderError("Groq returned an empty response")
        return content


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        super().__init__("gemini", model)
        try:
            import google.genai as genai

            self._client = genai.Client(api_key=api_key)
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise LLMProviderError("google-genai package not installed") from exc

    async def complete(self, messages: List[LLMMessage], **kwargs: Any) -> str:
        prompt = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)

        def _generate():
            return self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )

        response = await asyncio.to_thread(_generate)
        text = getattr(response, "text", None) or ""
        if not text:
            raise LLMProviderError("Gemini returned an empty response")
        return text


class OpenRouterProvider(LLMProvider):
    """OpenRouter chat completions provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "openrouter/auto",
        base_url: str = "https://openrouter.ai/api/v1",
    ):
        super().__init__("openrouter", model)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://genius.local",
                    "X-Title": "Genius",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0),
            )
        return self._client

    async def complete(self, messages: List[LLMMessage], **kwargs: Any) -> str:
        client = await self._get_client()
        response = await client.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.3),
                "max_tokens": kwargs.get("max_tokens", 4000),
            },
        )
        if response.status_code != 200:
            raise LLMProviderError(
                f"OpenRouter returned {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError("OpenRouter returned no choices")
        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise LLMProviderError("OpenRouter returned an empty response")
        return content


class RateLimiter:
    """Per-user fixed-window rate limiter with Redis + in-memory fallback."""

    def __init__(self, limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE):
        self.limit = limit_per_minute
        self._redis = None
        self._memory: Dict[str, List[Any]] = {}

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        redis_url = getattr(settings, "REDIS_URL", None) or None
        if not redis_url:
            return None
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            # Verify connectivity without blocking startup if Redis is down.
            await self._redis.ping()
            return self._redis
        except Exception as exc:
            logger.warning("Redis unavailable for LLM rate limiting, using memory: %s", exc)
            self._redis = False  # sentinel: redis explicitly unavailable
            return None

    async def is_allowed(self, user_id: Optional[int]) -> bool:
        """Return True if the user may make another request this window.

        When user_id is None (internal/caller-less usage) no limit is applied.
        """
        if user_id is None:
            return True
        redis = await self._get_redis()
        window = int(time.time() // RATE_LIMIT_WINDOW_SECONDS)
        key = f"llm:ratelimit:{user_id}:{window}"

        if redis:
            try:
                current = await redis.incr(key)  # type: ignore[attr-defined]
                if current == 1:
                    await redis.expire(key, RATE_LIMIT_WINDOW_SECONDS)  # type: ignore[attr-defined]
                return current <= self.limit
            except Exception as exc:
                logger.warning("Redis rate-limit check failed, falling back to memory: %s", exc)
                self._redis = False

        # In-memory fallback (process-local, not distributed).
        now_window = int(time.time() // RATE_LIMIT_WINDOW_SECONDS)
        entry = self._memory.get(str(user_id))
        if not entry or entry[0] != now_window:
            entry = [now_window, 0]
            self._memory[str(user_id)] = entry
        entry[1] += 1
        return entry[1] <= self.limit


class LLMService:
    """Facade that routes LLM calls through providers with fallback + rate limiting."""

    def __init__(self, rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE):
        self.rate_limiter = RateLimiter(rate_limit_per_minute)
        self.providers: List[LLMProvider] = []
        self._configure_providers()

    def _configure_providers(self):
        # Order matters: free/cheap providers first.
        if settings.GROQ_API_KEY:
            try:
                self.providers.append(
                    GroqProvider(
                        settings.GROQ_API_KEY,
                        model=getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                    )
                )
                logger.info("LLM provider configured: groq")
            except LLMProviderError as exc:
                logger.warning("Groq provider unavailable: %s", exc)

        if settings.GEMINI_API_KEY:
            try:
                self.providers.append(
                    GeminiProvider(
                        settings.GEMINI_API_KEY,
                        model=getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash"),
                    )
                )
                logger.info("LLM provider configured: gemini")
            except LLMProviderError as exc:
                logger.warning("Gemini provider unavailable: %s", exc)

        if getattr(settings, "OPENROUTER_API_KEY", None):
            try:
                self.providers.append(
                    OpenRouterProvider(
                        settings.OPENROUTER_API_KEY,
                        model=getattr(settings, "OPENROUTER_MODEL", "openrouter/auto"),
                    )
                )
                logger.info("LLM provider configured: openrouter")
            except LLMProviderError as exc:
                logger.warning("OpenRouter provider unavailable: %s", exc)

        if not self.providers:
            logger.warning(
                "No LLM providers configured. Set GROQ_API_KEY, GEMINI_API_KEY, "
                "or OPENROUTER_API_KEY."
            )

    async def complete_with_fallback(
        self,
        user_id: int,
        messages: List[LLMMessage],
        **kwargs: Any,
    ) -> str:
        """Run an LLM completion with per-user rate limiting and provider fallback."""
        if not self.rate_limiter.is_allowed(user_id):
            raise RateLimitExceeded(
                f"Rate limit exceeded: max {self.rate_limiter.limit} requests per minute per user"
            )

        last_error: Optional[Exception] = None
        for provider in self.providers:
            try:
                return await provider.complete(messages, **kwargs)
            except Exception as exc:
                logger.warning("LLM provider %s failed: %s", provider.name, exc)
                last_error = exc
                continue

        raise LLMProviderError(
            f"All LLM providers failed. Last error: {last_error}"
        ) if last_error else LLMProviderError("No LLM providers available")

    async def close(self):
        for provider in self.providers:
            client = getattr(provider, "_client", None)
            if client is not None and hasattr(client, "aclose"):
                try:
                    await client.aclose()
                except Exception:
                    pass


# Singleton instance
llm_service = LLMService()

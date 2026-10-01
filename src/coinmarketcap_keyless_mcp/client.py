"""Fixed-host, GET-only CoinMarketCap keyless HTTP client."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import random
import time
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import MappingProxyType
from typing import Any, Final

import httpx

from .contracts import BASE_URL, ROUTES
from .errors import CmcClientError, ErrorCode

RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_BACKOFF_BASE_SECONDS: Final = 0.25
DEFAULT_BACKOFF_MAX_SECONDS: Final = 2.0

Sleep = Callable[[float], Awaitable[None]]
RandomUniform = Callable[[float, float], float]
Monotonic = Callable[[], float]

logger = logging.getLogger(__name__)
_MAX_PROVIDER_ERROR_MESSAGE_CHARS: Final = 256


def _safe_provider_error_message(value: Any) -> str:
    """Keep provider diagnostics useful, bounded, and single-line."""

    if not isinstance(value, str) or not value:
        return "CoinMarketCap application error"
    safe = "".join(" " if ord(char) < 32 or 0x7F <= ord(char) <= 0x9F else char for char in value)
    safe = " ".join(safe.split())
    if not safe:
        return "CoinMarketCap application error"
    if len(safe) > _MAX_PROVIDER_ERROR_MESSAGE_CHARS:
        safe = safe[: _MAX_PROVIDER_ERROR_MESSAGE_CHARS - 1] + "…"
    return safe

CACHE_TTLS_BY_ROUTE: Final[Mapping[str, float]] = MappingProxyType(
    {
        ROUTES["cmc_crypto_map"]: 300.0,
        ROUTES["cmc_crypto_info"]: 300.0,
        ROUTES["cmc_quotes_latest"]: 30.0,
        ROUTES["cmc_listings_latest"]: 30.0,
        ROUTES["cmc_global_metrics_latest"]: 300.0,
        ROUTES["cmc_fear_greed_latest"]: 900.0,
        ROUTES["cmc_fear_greed_historical"]: 900.0,
        ROUTES["cmc_altcoin_season_latest"]: 900.0,
        ROUTES["cmc_altcoin_season_historical"]: 900.0,
        ROUTES["cmc_cmc100_latest"]: 300.0,
        ROUTES["cmc_cmc100_historical"]: 300.0,
        ROUTES["cmc_cmc20_latest"]: 300.0,
        ROUTES["cmc_cmc20_historical"]: 300.0,
    }
)
DEFAULT_MAX_CONCURRENCY: Final = 2
DEFAULT_MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024


def cache_key(route: str, params: Mapping[str, Any] | None = None) -> str:
    """Build a transparent key from a route and its effective serialized query."""

    query = serialize_query(params)
    return json.dumps(
        {"route": route, "query": sorted(query.items())},
        ensure_ascii=True,
        separators=(",", ":"),
    )


DEFAULT_CACHE_MAX_ENTRIES = 64


class _TtlCache:
    def __init__(self, now: Monotonic, max_entries: int = DEFAULT_CACHE_MAX_ENTRIES) -> None:
        self._now = now
        self._max_entries = max_entries
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= self._now():
                self._entries.pop(key, None)
                return None
            self._entries[key] = self._entries.pop(key)
            return copy.deepcopy(value)

    async def set(self, key: str, value: dict[str, Any], ttl: float) -> None:
        async with self._lock:
            now = self._now()
            self._entries.pop(key, None)
            for stale in [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]:
                del self._entries[stale]
            while len(self._entries) >= self._max_entries:
                del self._entries[next(iter(self._entries))]
            self._entries[key] = (now + ttl, copy.deepcopy(value))


def serialize_query(params: Mapping[str, Any] | None) -> dict[str, str]:
    """Serialize bounded tool query values into provider query strings."""

    if params is None:
        return {}
    result: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            result[key] = str(value).lower()
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            result[key] = ",".join(str(item) for item in value)
        else:
            result[key] = str(value)
    return result


def _validate_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _retry_after_seconds(value: str | None, maximum: float) -> float | None:
    if value is None:
        return None
    try:
        delay = float(value.strip())
        if not math.isfinite(delay):
            return None
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = (retry_at - datetime.now(UTC)).total_seconds()
    if delay < 0 or delay > maximum:
        return None
    return delay


class KeylessHttpClient:
    """An async client whose destination and method cannot be caller-controlled."""

    def __init__(
        self,
        *,
        timeout: httpx.Timeout | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
        cache_enabled: bool = True,
        cache_ttl_overrides: Mapping[str, float] | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        _transport: httpx.AsyncBaseTransport | None = None,
        _sleep: Sleep = asyncio.sleep,
        _random_uniform: RandomUniform = random.uniform,
        _monotonic: Monotonic = time.monotonic,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_base_seconds < 0 or backoff_max_seconds < 0:
            raise ValueError("backoff values must be non-negative")
        _validate_positive("max_concurrency", max_concurrency)
        _validate_positive("max_response_bytes", max_response_bytes)
        ttl_overrides = dict(cache_ttl_overrides or {})
        if any(route not in ROUTES.values() for route in ttl_overrides):
            raise ValueError("cache_ttl_overrides contains a non-allowlisted route")
        if any(
            isinstance(ttl, bool)
            or not isinstance(ttl, (int, float))
            or ttl < 0
            or not math.isfinite(ttl)
            for ttl in ttl_overrides.values()
        ):
            raise ValueError("cache TTLs must be finite and non-negative")
        self._max_attempts = max_attempts
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds
        self._sleep = _sleep
        self._random_uniform = _random_uniform
        self._cache_enabled = cache_enabled
        self._cache_ttls = {**CACHE_TTLS_BY_ROUTE, **ttl_overrides}
        self._cache = _TtlCache(_monotonic) if cache_enabled else None
        self._concurrency = asyncio.Semaphore(max_concurrency)
        self._max_response_bytes = max_response_bytes
        self._last_attempts = 0
        self._last_status_code: int | None = None
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
            timeout=timeout or httpx.Timeout(10.0, connect=5.0),
            transport=_transport,
        )

    async def __aenter__(self) -> "KeylessHttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, route: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """GET one exact allowlisted route and return its validated envelope."""

        if route not in ROUTES.values():
            raise CmcClientError(ErrorCode.INVALID_ARGUMENT, f"route is not allowlisted: {route!r}")

        query = serialize_query(params)
        key = cache_key(route, query)
        ttl = self._cache_ttls[route]
        if self._cache is not None and ttl > 0:
            cached = await self._cache.get(key)
            if cached is not None:
                logger.debug("cache hit route=%s", route)
                return cached
            logger.debug("cache miss route=%s", route)

        for attempt in range(1, self._max_attempts + 1):
            self._last_attempts = attempt
            try:
                async with self._concurrency:
                    async with self._http.stream("GET", route, params=query) as streamed:
                        # HTTP errors are classified from headers alone. Do not
                        # consume an error body or hold capacity during backoff.
                        response = streamed
                        if streamed.status_code < 400:
                            body = bytearray()
                            declared = streamed.headers.get("Content-Length")
                            if declared is not None and declared.isdecimal():
                                normalized_length = declared.lstrip("0") or "0"
                                maximum = str(self._max_response_bytes)
                                if len(normalized_length) > len(maximum) or (
                                    len(normalized_length) == len(maximum)
                                    and normalized_length > maximum
                                ):
                                    self._raise_oversized(streamed, attempt)
                            try:
                                async for chunk in _bounded_decoded_chunks(
                                    streamed, self._max_response_bytes
                                ):
                                    remaining = self._max_response_bytes + 1 - len(body)
                                    body.extend(chunk[:remaining])
                                    if len(body) > self._max_response_bytes:
                                        self._raise_oversized(streamed, attempt)
                            except zlib.error as exc:
                                raise CmcClientError(
                                    ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                                    "CoinMarketCap response has invalid compressed data",
                                    status_code=streamed.status_code,
                                    attempts=attempt,
                                ) from exc
                            response = httpx.Response(
                                streamed.status_code, content=bytes(body), request=streamed.request
                            )
            except httpx.TimeoutException as exc:
                if attempt < self._max_attempts:
                    await self._backoff(attempt)
                    continue
                raise CmcClientError(
                    ErrorCode.UPSTREAM_TIMEOUT,
                    "CoinMarketCap request timed out",
                    attempts=attempt,
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self._max_attempts:
                    await self._backoff(attempt)
                    continue
                raise CmcClientError(
                    ErrorCode.UPSTREAM_NETWORK_ERROR,
                    "CoinMarketCap request failed",
                    attempts=attempt,
                ) from exc

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_attempts:
                await self._retry_delay(response, attempt)
                continue
            self._last_status_code = response.status_code
            if response.status_code == 429:
                raise CmcClientError(
                    ErrorCode.RATE_LIMITED,
                    "CoinMarketCap rate limit exhausted",
                    status_code=response.status_code,
                    attempts=attempt,
                )
            if response.status_code >= 500:
                raise CmcClientError(
                    ErrorCode.UPSTREAM_5XX,
                    f"CoinMarketCap returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    attempts=attempt,
                )
            if response.status_code >= 400:
                raise CmcClientError(
                    ErrorCode.UPSTREAM_HTTP_ERROR,
                    f"CoinMarketCap returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    attempts=attempt,
                )
            result = self._parse_envelope(response, attempt)
            try:
                if self._cache is not None and ttl > 0:
                    await self._cache.set(key, result, ttl)
                return copy.deepcopy(result)
            except RecursionError as exc:
                raise CmcClientError(
                    ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                    "CoinMarketCap response structure is too deeply nested",
                    status_code=response.status_code,
                    attempts=attempt,
                ) from exc

        raise AssertionError("retry loop exhausted without a result")

    @staticmethod
    def _raise_oversized(response: httpx.Response, attempt: int) -> None:
        raise CmcClientError(
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response exceeds the configured size limit",
            status_code=response.status_code,
            attempts=attempt,
        )

    async def _retry_delay(self, response: httpx.Response, attempt: int) -> None:
        retry_after = _retry_after_seconds(
            response.headers.get("Retry-After"), self._backoff_max_seconds
        )
        if retry_after is not None:
            await self._sleep(retry_after)
            return
        ceiling = min(self._backoff_max_seconds, self._backoff_base_seconds * (2 ** (attempt - 1)))
        await self._sleep(self._random_uniform(0.0, ceiling))

    async def _backoff(self, attempt: int) -> None:
        ceiling = min(self._backoff_max_seconds, self._backoff_base_seconds * (2 ** (attempt - 1)))
        await self._sleep(self._random_uniform(0.0, ceiling))

    @staticmethod
    def _parse_envelope(response: httpx.Response, attempts: int) -> dict[str, Any]:
        try:
            payload = json.loads(response.content, object_pairs_hook=_unique_object)
        except (ValueError, TypeError, RecursionError) as exc:
            raise CmcClientError(
                ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                "CoinMarketCap response was not valid JSON",
                status_code=response.status_code,
                attempts=attempts,
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("status"), dict):
            raise CmcClientError(
                ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                "CoinMarketCap response is missing a valid status envelope",
                status_code=response.status_code,
                attempts=attempts,
            )
        status = payload["status"]
        if "error_code" not in status or "data" not in payload:
            raise CmcClientError(
                ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                "CoinMarketCap response is missing error_code or data",
                status_code=response.status_code,
                attempts=attempts,
            )
        error_code = status["error_code"]
        if isinstance(error_code, bool) or not isinstance(error_code, (int, float, str)):
            raise CmcClientError(
                ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                "CoinMarketCap response has an invalid error_code",
                status_code=response.status_code,
                attempts=attempts,
            )
        is_success = (
            (isinstance(error_code, str) and error_code.strip() == "0")
            or (isinstance(error_code, (int, float)) and error_code == 0)
        )
        if not is_success:
            raise CmcClientError(
                ErrorCode.UPSTREAM_APPLICATION_ERROR,
                _safe_provider_error_message(status.get("error_message")),
                status_code=response.status_code,
                attempts=attempts,
                provider_error_code=error_code,
            )
        return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


async def _bounded_decoded_chunks(
    response: httpx.Response, maximum: int
) -> AsyncIterator[bytes]:
    """Decode advertised encodings without allowing an unbounded output chunk."""

    if response.is_stream_consumed:
        yield response.content[: maximum + 1]
        return
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding in {"", "identity"}:
        async for chunk in response.aiter_raw():
            yield chunk[: maximum + 1]
        return
    if encoding == "gzip":
        decoder = zlib.decompressobj(zlib.MAX_WBITS | 16)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
    else:
        raise CmcClientError(
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response uses an unsupported content encoding",
            status_code=response.status_code,
        )
    produced = 0
    async for raw_chunk in response.aiter_raw():
        remaining = maximum + 1 - produced
        decoded = decoder.decompress(raw_chunk, remaining)
        produced += len(decoded)
        if decoded:
            yield decoded
        if produced > maximum:
            return
        while decoder.unconsumed_tail:
            remaining = maximum + 1 - produced
            decoded = decoder.decompress(decoder.unconsumed_tail, remaining)
            produced += len(decoded)
            if decoded:
                yield decoded
            if produced > maximum:
                return
    remaining = maximum + 1 - produced
    tail = decoder.flush(remaining)
    if tail:
        yield tail

"""Fixed-host, GET-only CoinMarketCap keyless HTTP client."""

from __future__ import annotations

import asyncio
import contextvars
import copy
import json
import logging
import math
import random
import time
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
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
DEFAULT_REQUEST_DEADLINE_SECONDS: Final = 30.0
_MAX_ERROR_BODY_BYTES: Final = 4096
# Bodies above this size are parsed off the event loop so one large payload
# cannot stall other in-flight tool calls.
_THREADED_PARSE_THRESHOLD_BYTES: Final = 64 * 1024
# Explicit, version-independent bound: json.loads nesting limits differ by Python version.
MAX_JSON_DEPTH: Final = 256

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


def _http_error_detail(body: bytes) -> str | None:
    """Extract a provider error message from a small 4xx body, if it has one."""

    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    message = status.get("error_message") if isinstance(status, dict) else None
    if not isinstance(message, str) or not message.strip():
        message = payload.get("error_message")
    if not isinstance(message, str) or not message.strip():
        return None
    return _safe_provider_error_message(message)


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
        self._entries: dict[str, tuple[float, Any]] = {}

    # Neither method awaits, so each runs atomically on the event loop.
    async def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._now():
            self._entries.pop(key, None)
            return None
        self._entries[key] = self._entries.pop(key)
        return copy.deepcopy(value)

    async def set(self, key: str, value: Any, ttl: float) -> None:
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
    delay = _parse_retry_after(value)
    if delay is None or delay > maximum:
        return None
    return delay


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a non-negative finite Retry-After delay, without applying a cap."""

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
    if delay < 0:
        return None
    return delay


@dataclass
class _Inflight:
    task: asyncio.Task[tuple[dict[str, Any], bytes, int, int]]
    waiters: int = 0


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
        request_deadline_seconds: float = DEFAULT_REQUEST_DEADLINE_SECONDS,
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
        if not math.isfinite(request_deadline_seconds) or request_deadline_seconds <= 0:
            raise ValueError("request_deadline_seconds must be finite and greater than zero")
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
        self._request_deadline_seconds = request_deadline_seconds
        self._inflight: dict[str, _Inflight] = {}
        # Per-task call metadata, so concurrent calls cannot overwrite each other's.
        self._last_call: contextvars.ContextVar[tuple[int, int | None]] = contextvars.ContextVar(
            f"cmc_last_call_{id(self)}", default=(0, None)
        )
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

    @property
    def _last_attempts(self) -> int:
        return self._last_call.get()[0]

    @property
    def _last_status_code(self) -> int | None:
        return self._last_call.get()[1]

    async def aclose(self) -> None:
        for entry in list(self._inflight.values()):
            entry.task.cancel()
        await self._http.aclose()

    async def get(self, route: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """GET one exact allowlisted route and return its validated envelope."""

        if route not in ROUTES.values():
            raise CmcClientError(ErrorCode.INVALID_ARGUMENT, f"route is not allowlisted: {route!r}")

        query = serialize_query(params)
        key = cache_key(route, query)
        ttl = self._cache_ttls[route]
        if self._cache is None or ttl <= 0:
            result, _, status_code, attempts = await self._fetch(route, query, key, ttl)
            self._last_call.set((attempts, status_code))
            return result

        cached = await self._cache.get(key)
        if cached is not None:
            logger.debug("cache hit route=%s", route)
            return await self._parse(cached, 200, 0)
        logger.debug("cache miss route=%s", route)

        # Identical concurrent cold requests share one upstream fetch, which is
        # cancelled only once every caller waiting on it has been cancelled.
        entry = self._inflight.get(key)
        leader = entry is None
        if entry is None:
            entry = _Inflight(asyncio.create_task(self._fetch(route, query, key, ttl)))
            self._inflight[key] = entry
            entry.task.add_done_callback(lambda done: self._finish_inflight(key, done))
        entry.waiters += 1
        try:
            result, body, status_code, attempts = await asyncio.shield(entry.task)
        finally:
            entry.waiters -= 1
            if entry.waiters == 0 and not entry.task.done():
                entry.task.cancel()
                await asyncio.wait({entry.task})
        self._last_call.set((attempts, status_code))
        return result if leader else await self._parse(body, status_code, attempts)

    def _finish_inflight(self, key: str, task: asyncio.Task[Any]) -> None:
        entry = self._inflight.get(key)
        if entry is not None and entry.task is task:
            del self._inflight[key]
        if not task.cancelled():
            task.exception()  # Mark retrieved even when every waiter was cancelled.

    async def _fetch(
        self, route: str, query: dict[str, str], key: str, ttl: float
    ) -> tuple[dict[str, Any], bytes, int, int]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with self._concurrency, asyncio.timeout(self._request_deadline_seconds):
                    async with self._http.stream("GET", route, params=query) as streamed:
                        # Retryable errors are classified from headers alone, so
                        # capacity is never held while reading them or backing off.
                        response = streamed
                        error_detail: str | None = None
                        if 400 <= streamed.status_code < 500 and streamed.status_code != 429:
                            error_detail = await self._read_error_detail(streamed)
                        elif streamed.status_code < 400:
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
            except (httpx.TimeoutException, TimeoutError) as exc:
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

            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < self._max_attempts
                and await self._retry_delay(response, attempt)
            ):
                continue
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
                message = f"CoinMarketCap returned HTTP {response.status_code}"
                raise CmcClientError(
                    ErrorCode.UPSTREAM_HTTP_ERROR,
                    f"{message}: {error_detail}" if error_detail else message,
                    status_code=response.status_code,
                    attempts=attempt,
                )
            result = await self._parse(response.content, response.status_code, attempt)
            if self._cache is not None and ttl > 0:
                # Cache the validated bytes: immutable, and a hit re-parses
                # instead of deep-copying a large object graph.
                await self._cache.set(key, response.content, ttl)
            return result, response.content, response.status_code, attempt

        raise AssertionError("retry loop exhausted without a result")

    @staticmethod
    def _raise_oversized(response: httpx.Response, attempt: int) -> None:
        raise CmcClientError(
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response exceeds the configured size limit",
            status_code=response.status_code,
            attempts=attempt,
        )

    async def _retry_delay(self, response: httpx.Response, attempt: int) -> bool:
        """Sleep before a retry, or return False when the provider asks for longer."""

        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            if retry_after > self._backoff_max_seconds:
                # Retrying sooner than the provider asked only burns the limit.
                return False
            await self._sleep(retry_after)
            return True
        await self._backoff(attempt)
        return True

    async def _read_error_detail(self, response: httpx.Response) -> str | None:
        body = bytearray()
        try:
            async for chunk in _bounded_decoded_chunks(response, _MAX_ERROR_BODY_BYTES):
                body.extend(chunk)
                if len(body) > _MAX_ERROR_BODY_BYTES:
                    return None
        except (zlib.error, CmcClientError):
            return None
        return _http_error_detail(bytes(body))

    async def _parse(self, body: bytes, status_code: int, attempts: int) -> dict[str, Any]:
        response = httpx.Response(status_code, content=body)
        if len(body) > _THREADED_PARSE_THRESHOLD_BYTES:
            return await asyncio.to_thread(self._parse_envelope, response, attempts)
        return self._parse_envelope(response, attempts)

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

        if _json_depth_exceeds(payload, MAX_JSON_DEPTH):
            raise CmcClientError(
                ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
                "CoinMarketCap response structure is too deeply nested",
                status_code=response.status_code,
                attempts=attempts,
            )
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
        is_success = (isinstance(error_code, str) and error_code.strip() == "0") or (
            isinstance(error_code, (int, float)) and error_code == 0
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


def _json_depth_exceeds(value: Any, maximum: int) -> bool:
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        if depth > maximum:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


async def _bounded_decoded_chunks(response: httpx.Response, maximum: int) -> AsyncIterator[bytes]:
    """Decode advertised encodings without allowing an unbounded output chunk."""

    if response.is_stream_consumed:
        yield response.content[: maximum + 1]
        return
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding in {"", "identity"}:
        async for chunk in response.aiter_raw():
            yield chunk[: maximum + 1]
        return
    if encoding not in {"gzip", "deflate"}:
        raise CmcClientError(
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response uses an unsupported content encoding",
            status_code=response.status_code,
        )
    decoder: Any = None
    header = b""
    produced = 0
    async for raw_chunk in response.aiter_raw():
        pending = raw_chunk
        if decoder is None:
            header += pending
            if encoding == "deflate" and len(header) < 2:
                continue
            decoder = zlib.decompressobj(_wbits(encoding, header))
            pending = header
        while pending and produced <= maximum:
            decoded = decoder.decompress(pending, maximum + 1 - produced)
            produced += len(decoded)
            if decoded:
                yield decoded
            if decoder.eof:
                pending = decoder.unused_data
                if not pending or encoding != "gzip":
                    break
                # Multi-member gzip: each member is a complete stream.
                decoder = zlib.decompressobj(zlib.MAX_WBITS | 16)
            else:
                pending = decoder.unconsumed_tail
        if produced > maximum:
            return
    if decoder is None:
        if header:
            decoder = zlib.decompressobj(_wbits(encoding, header))
            decoded = decoder.decompress(header, maximum + 1)
            if decoded:
                yield decoded
        else:
            return
    tail = decoder.flush(maximum + 1 - produced)
    if tail:
        yield tail


def _wbits(encoding: str, header: bytes) -> int:
    if encoding == "gzip":
        return zlib.MAX_WBITS | 16
    # Content-Encoding: deflate is meant to be zlib-wrapped, but some servers
    # send raw deflate. A zlib header is CM=8 with a check value divisible by 31.
    if len(header) >= 2 and header[0] & 0x0F == 8 and (header[0] << 8 | header[1]) % 31 == 0:
        return zlib.MAX_WBITS
    return -zlib.MAX_WBITS

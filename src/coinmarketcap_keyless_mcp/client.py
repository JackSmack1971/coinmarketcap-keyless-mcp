"""Fixed-host, GET-only CoinMarketCap keyless HTTP client."""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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
        _transport: httpx.AsyncBaseTransport | None = None,
        _sleep: Sleep = asyncio.sleep,
        _random_uniform: RandomUniform = random.uniform,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_base_seconds < 0 or backoff_max_seconds < 0:
            raise ValueError("backoff values must be non-negative")
        self._max_attempts = max_attempts
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds
        self._sleep = _sleep
        self._random_uniform = _random_uniform
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json"},
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
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._http.get(route, params=query)
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
            return self._parse_envelope(response, attempt)

        raise AssertionError("retry loop exhausted without a result")

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
            payload = response.json()
        except (ValueError, TypeError) as exc:
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
                str(status.get("error_message") or "CoinMarketCap application error"),
                status_code=response.status_code,
                attempts=attempts,
                provider_error_code=error_code,
            )
        return payload

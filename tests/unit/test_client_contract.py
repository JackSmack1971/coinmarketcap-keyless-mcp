"""Exact error details, boundaries, and defaults of the keyless client.

These pin observable details that coarser tests leave open: error messages,
status codes and attempt counts (they reach MCP tool errors and live-evidence
reports), size/depth/Retry-After boundaries, and decoder output bounds.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import zlib
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from coinmarketcap_keyless_mcp.client import (
    MAX_JSON_DEPTH,
    KeylessHttpClient,
    _bounded_decoded_chunks,
    _parse_retry_after,
    _safe_provider_error_message,
    _TtlCache,
    cache_key,
)
from coinmarketcap_keyless_mcp.contracts import ROUTES
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode

ROUTE = ROUTES["cmc_quotes_latest"]
OTHER_ROUTE = ROUTES["cmc_global_metrics_latest"]
VALID = {"status": {"error_code": 0}, "data": {"items": []}}


class CountingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.consumed = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed += len(chunk)
            yield chunk


def chunked(body: bytes, size: int) -> list[bytes]:
    return [body[index : index + size] for index in range(0, len(body), size)]


async def no_sleep(delay: float) -> None:
    return None


def _raise(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


def _body(content: bytes, status: int = 200, headers: dict[str, str] | None = None):
    return lambda request: httpx.Response(status, headers=headers, stream=CountingStream([content]))


def _deep(depth: int) -> bytes:
    # The root object is depth 1 and "data" is depth 2, so `depth - 1` lists
    # make the deepest container sit at exactly `depth`.
    lists = depth - 1
    return b'{"status":{"error_code":0},"data":' + b"[" * lists + b"]" * lists + b"}"


ERROR_CASES = {
    "timeout": (
        _raise(httpx.ReadTimeout("fixture")),
        (ErrorCode.UPSTREAM_TIMEOUT, "CoinMarketCap request timed out", None, 2, None),
    ),
    "network": (
        _raise(httpx.ConnectError("fixture")),
        (ErrorCode.UPSTREAM_NETWORK_ERROR, "CoinMarketCap request failed", None, 2, None),
    ),
    "429": (
        _body(b"", 429),
        (ErrorCode.RATE_LIMITED, "CoinMarketCap rate limit exhausted", 429, 2, None),
    ),
    "503": (
        _body(b"", 503),
        (ErrorCode.UPSTREAM_5XX, "CoinMarketCap returned HTTP 503", 503, 2, None),
    ),
    "404": (
        _body(b"", 404),
        (ErrorCode.UPSTREAM_HTTP_ERROR, "CoinMarketCap returned HTTP 404", 404, 1, None),
    ),
    "not-json": (
        _body(b"not json"),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response was not valid JSON",
            200,
            1,
            None,
        ),
    ),
    "duplicate-key": (
        _body(b'{"status":{"error_code":0},"data":[],"data":[]}'),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response was not valid JSON",
            200,
            1,
            None,
        ),
    ),
    "no-envelope": (
        _body(b"[]"),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response is missing a valid status envelope",
            200,
            1,
            None,
        ),
    ),
    "no-data": (
        _body(b'{"status":{"error_code":0}}'),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response is missing error_code or data",
            200,
            1,
            None,
        ),
    ),
    "bad-error-code": (
        _body(b'{"status":{"error_code":true},"data":[]}'),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response has an invalid error_code",
            200,
            1,
            None,
        ),
    ),
    "application": (
        _body(b'{"status":{"error_code":1006,"error_message":"bad id"},"data":null}'),
        (ErrorCode.UPSTREAM_APPLICATION_ERROR, "bad id", 200, 1, 1006),
    ),
    "too-deep": (
        _body(_deep(MAX_JSON_DEPTH + 1)),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response structure is too deeply nested",
            200,
            1,
            None,
        ),
    ),
    "oversized-body": (
        _body(b" " * 1025),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response exceeds the configured size limit",
            200,
            1,
            None,
        ),
    ),
    "oversized-header": (
        _body(b"{}", headers={"Content-Length": "1025"}),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response exceeds the configured size limit",
            200,
            1,
            None,
        ),
    ),
    "bad-gzip": (
        _body(b"definitely not gzip", headers={"Content-Encoding": "gzip"}),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response has invalid compressed data",
            200,
            1,
            None,
        ),
    ),
    "unsupported-encoding": (
        _body(b"{}", headers={"Content-Encoding": "br"}),
        (
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            "CoinMarketCap response uses an unsupported content encoding",
            200,
            1,
            None,
        ),
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(ERROR_CASES))
async def test_every_error_path_reports_exact_details(case: str) -> None:
    handler, expected = ERROR_CASES[case]
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler),
        max_attempts=2,
        max_response_bytes=1024,
        _sleep=no_sleep,
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    error = caught.value
    assert (
        error.code,
        error.message,
        error.status_code,
        error.attempts,
        error.provider_error_code,
    ) == expected
    assert str(error) == error.message


@pytest.mark.asyncio
async def test_large_invalid_payload_parsed_off_loop_keeps_error_details() -> None:
    body = b'{"status":' + b" " * (128 * 1024)
    async with KeylessHttpClient(_transport=httpx.MockTransport(_body(body))) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert (caught.value.status_code, caught.value.attempts) == (200, 1)


def test_client_error_defaults() -> None:
    error = CmcClientError(ErrorCode.INTERNAL_ERROR, "message", details={"k": 1})
    assert (error.attempts, error.status_code, error.provider_error_code) == (1, None, None)
    assert error.details == {"k": 1}
    assert str(error) == "message"
    assert CmcClientError(ErrorCode.INTERNAL_ERROR, "m", status_code=418).status_code == 418


@pytest.mark.asyncio
async def test_non_allowlisted_route_message() -> None:
    async with KeylessHttpClient(_transport=httpx.MockTransport(_body(b"{}"))) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get("/v1/other")
    assert caught.value.message == "route is not allowlisted: '/v1/other'"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts must be at least 1"),
        ({"backoff_base_seconds": -1}, "backoff values must be non-negative"),
        ({"max_concurrency": 0}, "max_concurrency must be greater than zero"),
        ({"max_response_bytes": 0}, "max_response_bytes must be greater than zero"),
        (
            {"request_deadline_seconds": 0},
            "request_deadline_seconds must be finite and greater than zero",
        ),
        (
            {"cache_ttl_overrides": {"/v1/other": 1.0}},
            "cache_ttl_overrides contains a non-allowlisted route",
        ),
        ({"cache_ttl_overrides": {ROUTE: -1.0}}, "cache TTLs must be finite and non-negative"),
    ],
)
def test_constructor_rejections_have_exact_messages(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError) as caught:
        KeylessHttpClient(**kwargs)
    assert str(caught.value) == message


@pytest.mark.asyncio
async def test_default_headers_timeout_and_call_metadata() -> None:
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(_body(json.dumps(VALID).encode()))
    ) as client:
        assert client._http.headers["accept"] == "application/json"
        assert client._http.headers["accept-encoding"] == "gzip, deflate"
        assert client._http.timeout == httpx.Timeout(10.0, connect=5.0)
        assert (client._last_attempts, client._last_status_code) == (0, None)
        await client.get(ROUTE)
        assert (client._last_attempts, client._last_status_code) == (1, 200)


@pytest.mark.asyncio
@pytest.mark.parametrize(("ttl", "cached"), [(0.0, False), (0.5, True)])
async def test_ttl_override_boundaries(ttl: float, cached: bool) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=VALID)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_ttl_overrides={ROUTE: ttl}
    ) as client:
        assert await client.get(ROUTE) == VALID
        assert await client.get(ROUTE) == VALID
        assert len(client._cache._entries) == (1 if cached else 0)
    assert calls == (1 if cached else 2)


@pytest.mark.asyncio
async def test_cache_is_keyed_by_route_as_well_as_query(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": request.url.path})

    caplog.set_level(logging.DEBUG, logger="coinmarketcap_keyless_mcp.client")
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        first = await client.get(ROUTE, {"convert": "USD"})
        second = await client.get(OTHER_ROUTE, {"convert": "USD"})
        again = await client.get(ROUTE, {"convert": "USD"})
    assert first["data"].endswith(ROUTE) and second["data"].endswith(OTHER_ROUTE)
    assert again == first
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        f"cache miss route={ROUTE}",
        f"cache miss route={OTHER_ROUTE}",
        f"cache hit route={ROUTE}",
    ]


def test_cache_key_format_is_exact() -> None:
    assert cache_key(ROUTE, {"b": [1, 2], "a": "é"}) == (
        '{"route":"' + ROUTE + '","query":[["a","\\u00e9"],["b","1,2"]]}'
    )


@pytest.mark.asyncio
async def test_ttl_cache_order_expiry_and_copies() -> None:
    now = [0.0]
    cache = _TtlCache(lambda: now[0], max_entries=2)
    await cache.set("a", {"v": []}, 10.0)
    await cache.set("b", {"v": []}, 1.0)
    await cache.set("a", {"v": []}, 10.0)  # Re-setting moves "a" to most recent.
    assert list(cache._entries) == ["b", "a"]
    now[0] = 1.0  # "b" expires exactly now and is purged instead of evicting "a".
    await cache.set("c", {"v": []}, 10.0)
    assert list(cache._entries) == ["a", "c"]
    value = await cache.get("a")
    value["v"].append("mutation")
    assert await cache.get("a") == {"v": []}


@pytest.mark.asyncio
async def test_coalesced_followers_get_independent_copies() -> None:
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(200, json=VALID)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        tasks = [asyncio.create_task(client.get(ROUTE)) for _ in range(3)]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*tasks)
    for index, result in enumerate(results):
        result["data"]["items"].append(index)
    assert [result["data"]["items"] for result in results] == [[0], [1], [2]]


@pytest.mark.asyncio
async def test_content_length_comparison_handles_trailing_and_leading_zeros() -> None:
    oversized = CountingStream([b" " * 10])
    padded = json.dumps(VALID).encode()
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, headers={"Content-Length": "3000000"}, stream=oversized)
                if request.url.params.get("case") == "big"
                else httpx.Response(
                    200,
                    headers={"Content-Length": "0" * 40 + str(len(padded))},
                    stream=CountingStream([padded]),
                )
            )
        )
    ) as client:
        with pytest.raises(CmcClientError):
            await client.get(ROUTE, {"case": "big"})
        assert await client.get(ROUTE, {"case": "padded"}) == VALID
    assert oversized.consumed == 0


@pytest.mark.asyncio
async def test_5xx_body_is_not_read() -> None:
    stream = CountingStream([b"x" * 100])
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: httpx.Response(500, stream=stream))
    ) as client:
        with pytest.raises(CmcClientError):
            await client.get(ROUTE)
    assert stream.consumed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["", "gzip"])
async def test_body_exactly_at_the_size_limit_is_accepted(encoding: str) -> None:
    body = json.dumps(VALID).encode()
    raw = gzip.compress(body) if encoding else body
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Encoding": encoding}, stream=CountingStream([raw])
            )
        ),
        max_response_bytes=len(body),
    ) as client:
        assert await client.get(ROUTE) == VALID


@pytest.mark.asyncio
async def test_retry_after_exactly_at_the_cap_is_honored() -> None:
    delays: list[float] = []
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json=VALID)]
    )

    async def record(delay: float) -> None:
        delays.append(delay)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: next(responses)),
        backoff_max_seconds=2.0,
        _sleep=record,
    ) as client:
        assert await client.get(ROUTE) == VALID
    assert delays == [2.0]


def test_retry_after_http_date_without_zone_is_utc() -> None:
    target = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=90)
    header = format_datetime(target.replace(tzinfo=None))  # "-0000": no zone information.
    assert header.endswith("-0000")
    delay = _parse_retry_after(header)
    assert delay is not None and 80 <= delay <= 90


@pytest.mark.asyncio
@pytest.mark.parametrize(("padding", "included"), [(0, True), (1, False)])
async def test_error_body_read_limit_boundary(padding: int, included: bool) -> None:
    prefix = b'{"error_message":"why'
    suffix = b'"}'
    body = prefix + b"y" * (4096 - len(prefix) - len(suffix) + padding) + suffix
    async with KeylessHttpClient(_transport=httpx.MockTransport(_body(body, 400))) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert caught.value.message.startswith("CoinMarketCap returned HTTP 400: why") is included


@pytest.mark.asyncio
async def test_depth_limit_boundary_and_scan_continues_past_scalars() -> None:
    at_limit = _deep(MAX_JSON_DEPTH)
    lists = MAX_JSON_DEPTH
    scalar_last = b'{"status":{"error_code":0},"data":' + b"[" * lists + b"]" * lists + b',"z":1}'
    bodies = iter([at_limit, scalar_last])
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: httpx.Response(200, content=next(bodies))),
        cache_enabled=False,
    ) as client:
        assert (await client.get(ROUTE))["status"] == {"error_code": 0}
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert caught.value.message == "CoinMarketCap response structure is too deeply nested"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a\x7fb", "a b"),
        ("a\x9fb", "a b"),
        ("a\x1fb", "a b"),
        ("a\xa0b", "a b"),
        (123, "CoinMarketCap application error"),
        ("", "CoinMarketCap application error"),
        ("\x00\x01", "CoinMarketCap application error"),
        ("x" * 256, "x" * 256),
        ("x" * 257, "x" * 255 + "…"),
    ],
)
def test_provider_error_message_sanitizing(value: object, expected: str) -> None:
    assert _safe_provider_error_message(value) == expected


async def _decode(raw_chunks: list[bytes], encoding: str, maximum: int) -> list[bytes]:
    response = httpx.Response(
        200, headers={"Content-Encoding": encoding}, stream=CountingStream(raw_chunks)
    )
    return [chunk async for chunk in _bounded_decoded_chunks(response, maximum)]


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_decoder_output_never_exceeds_limit_plus_one(encoding: str) -> None:
    expanded = b"\x00" * (4 * 1024 * 1024)
    raw = gzip.compress(expanded) if encoding == "gzip" else zlib.compress(expanded)
    chunks = await _decode(chunked(raw, 512), encoding, 1000)
    assert all(len(chunk) <= 1001 for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) == 1001


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["zlib", "raw"])
async def test_deflate_decodes_one_byte_chunks_and_ignores_trailing_bytes(variant: str) -> None:
    body = json.dumps(VALID).encode()
    if variant == "zlib":
        raw = zlib.compress(body)
    else:
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        raw = compressor.compress(body) + compressor.flush()
    decoded = await _decode(chunked(raw + b"trailing", 1), "deflate", 10_000)
    assert b"".join(decoded) == body


@pytest.mark.asyncio
async def test_single_byte_deflate_body_and_empty_encoding_header() -> None:
    assert await _decode([b"\x03"], "deflate", 100) == []  # Raw deflate of an empty body.
    assert b"".join(await _decode([b'{"a":1}'], "", 100)) == b'{"a":1}'

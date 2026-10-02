import asyncio
import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from coinmarketcap_keyless_mcp.client import (
    CACHE_TTLS_BY_ROUTE,
    DEFAULT_MAX_CONCURRENCY,
    KeylessHttpClient,
    _retry_after_seconds,
    cache_key,
    serialize_query,
)
from coinmarketcap_keyless_mcp.contracts import BASE_URL, ROUTES
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode


def response(
    payload: object, status_code: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers=headers)


async def run_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    async with KeylessHttpClient(_transport=transport, **kwargs) as client:
        return await client.get(
            ROUTES["cmc_quotes_latest"], {"ids": [1, 1027], "skip_invalid": False}
        )


def test_query_serialization() -> None:
    assert serialize_query({"ids": [1, 1027], "omit": None, "skip_invalid": False}) == {
        "ids": "1,1027",
        "skip_invalid": "false",
    }


def test_cache_keys_are_deterministic_and_normalized() -> None:
    route = ROUTES["cmc_quotes_latest"]
    assert cache_key(route, {"ids": [1, 1027], "skip_invalid": False}) == cache_key(
        route, {"skip_invalid": False, "ids": [1, 1027]}
    )
    assert cache_key(route, {"ids": [1, 1027]}) == cache_key(route, {"ids": "1,1027"})
    assert cache_key(route, {"ids": [1]}) != cache_key(route, {"ids": [2]})
    assert cache_key(route, {"ids": [1]}) != cache_key(ROUTES["cmc_crypto_info"], {"ids": [1]})
    assert cache_key(route, {}) != cache_key(route, {"skip_invalid": False})


def test_cache_ttl_policy_is_route_authoritative() -> None:
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_crypto_map"]] == 300
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_quotes_latest"]] == 30
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_global_metrics_latest"]] == 300
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_fear_greed_latest"]] == 900
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_altcoin_season_historical"]] == 900
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_cmc20_historical"]] == 300


def test_e1r_cache_ttls_are_pinned_and_cover_every_route() -> None:
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_simple_price"]] == 30
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_crypto_categories"]] == 300
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_crypto_category"]] == 300
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_price_conversion"]] == 30
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_exchange_map"]] == 300
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_dex_platform_list"]] == 900
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_dex_token_price"]] == 15
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_dex_token"]] == 15
    assert CACHE_TTLS_BY_ROUTE[ROUTES["cmc_dex_platform_detail"]] == 900
    assert set(CACHE_TTLS_BY_ROUTE) == set(ROUTES.values())
    assert len(CACHE_TTLS_BY_ROUTE) == 22


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"backoff_base_seconds": -0.1}, "backoff values"),
        ({"backoff_max_seconds": -0.1}, "backoff values"),
        ({"max_concurrency": 0}, "max_concurrency"),
        ({"max_concurrency": -1}, "max_concurrency"),
        ({"max_response_bytes": 0}, "max_response_bytes"),
        ({"cache_ttl_overrides": {ROUTES["cmc_quotes_latest"]: -1}}, "cache TTLs"),
        ({"cache_ttl_overrides": {ROUTES["cmc_quotes_latest"]: "not-a-number"}}, "cache TTLs"),
        ({"cache_ttl_overrides": {"/not-allowlisted": 1}}, "non-allowlisted"),
    ],
)
def test_phase3_configuration_rejects_invalid_values(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        KeylessHttpClient(_transport=httpx.MockTransport(lambda request: response({})), **kwargs)


def test_default_concurrency_is_two() -> None:
    client = KeylessHttpClient(_transport=httpx.MockTransport(lambda request: response({})))
    assert DEFAULT_MAX_CONCURRENCY == 2
    assert client._concurrency._value == 2  # noqa: SLF001


@pytest.mark.asyncio
async def test_zero_backoff_bounds_are_allowed() -> None:
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: response({})),
        backoff_base_seconds=0,
        backoff_max_seconds=0,
    ) as client:
        assert client._backoff_base_seconds == 0
        assert client._backoff_max_seconds == 0


@pytest.mark.asyncio
async def test_default_http_timeouts_are_finite() -> None:
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: response({}))
    ) as client:
        timeout = client._http.timeout
        assert isinstance(timeout, httpx.Timeout)
        assert all(
            value is not None
            for value in (timeout.connect, timeout.read, timeout.write, timeout.pool)
        )


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_fixed_base_url_get_and_no_auth_header() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    result = await run_client(handler)
    assert result["data"] == {"ok": True}
    assert seen["method"] == "GET"
    assert (
        seen["url"] == f"{BASE_URL}/v3/cryptocurrency/quotes/latest?ids=1%2C1027&skip_invalid=false"
    )
    assert "x-cmc_pro_api_key" not in seen["headers"]
    assert "authorization" not in seen["headers"]


@pytest.mark.asyncio
async def test_successful_response_is_cached_and_cached_values_are_isolated() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response({"status": {"error_code": 0}, "data": {"items": []}})

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        first = await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        first["data"]["items"].append("caller mutation")
        second = await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
    assert calls == 1
    assert second["data"] == {"items": []}


@pytest.mark.asyncio
async def test_cache_expiration_refreshes_upstream_value() -> None:
    clock = Clock()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response({"status": {"error_code": 0}, "data": {"call": calls}})

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler),
        _monotonic=clock,
        cache_ttl_overrides={ROUTES["cmc_quotes_latest"]: 5},
    ) as client:
        assert (await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]}))["data"]["call"] == 1
        clock.value = 4.99
        assert (await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]}))["data"]["call"] == 1
        clock.value = 5
        assert (await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]}))["data"]["call"] == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_cache_disabled_always_reaches_upstream() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response({"status": {"error_code": 0}, "data": {"call": calls}})

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False
    ) as client:
        await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (httpx.Response(400), ErrorCode.UPSTREAM_HTTP_ERROR),
        (httpx.Response(429), ErrorCode.RATE_LIMITED),
        (httpx.Response(503), ErrorCode.UPSTREAM_5XX),
        (
            httpx.Response(200, json={"status": {"error_code": 1006}, "data": None}),
            ErrorCode.UPSTREAM_APPLICATION_ERROR,
        ),
        (
            httpx.Response(200, json={"status": {"error_code": 0}}),
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
        ),
    ],
)
async def test_failures_are_never_cached(failure: httpx.Response, expected_code: ErrorCode) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return failure
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), max_attempts=1) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        assert caught.value.code is expected_code
        assert (await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]}))["data"] == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_exception", "expected_code"),
    [
        (httpx.ReadTimeout("timed out"), CmcClientError, ErrorCode.UPSTREAM_TIMEOUT),
        (httpx.ConnectError("network"), CmcClientError, ErrorCode.UPSTREAM_NETWORK_ERROR),
        (RuntimeError("internal"), RuntimeError, None),
    ],
)
async def test_exception_failures_are_never_cached(
    failure: Exception, expected_exception: type[Exception], expected_code: ErrorCode | None
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise failure
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), max_attempts=1) as client:
        with pytest.raises(expected_exception) as caught:
            await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        if expected_code is not None:
            assert isinstance(caught.value, CmcClientError)
            assert caught.value.code is expected_code
        assert (await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]}))["data"] == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_response_size_limit_rejects_oversized_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": 0}, "data": {"payload": "x" * 20}})

    with pytest.raises(CmcClientError) as caught:
        async with KeylessHttpClient(
            _transport=httpx.MockTransport(handler), max_response_bytes=10
        ) as client:
            await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
async def test_concurrency_bound_is_applied_to_actual_upstream_calls() -> None:
    active = 0
    maximum = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 2:
            started.set()
        await release.wait()
        active -= 1
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False, max_concurrency=2
    ) as client:
        tasks = [
            asyncio.create_task(client.get(ROUTES["cmc_quotes_latest"], {"ids": [i]}))
            for i in range(5)
        ]
        await started.wait()
        assert active == 2
        release.set()
        await asyncio.gather(*tasks)
    assert maximum == 2


@pytest.mark.asyncio
async def test_concurrency_slot_releases_after_exception_and_cache_hit_does_not_consume_it() -> (
    None
):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), max_attempts=1, max_concurrency=1
    ) as client:
        with pytest.raises(CmcClientError):
            await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        assert client._concurrency._value == 1  # noqa: SLF001
        await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
        assert client._concurrency._value == 1  # noqa: SLF001
    assert calls == 2


@pytest.mark.asyncio
async def test_info_logging_does_not_dump_provider_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_market_payload = "provider-payload-that-must-not-be-logged"

    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": 0}, "data": {"payload": secret_market_payload}})

    with caplog.at_level(logging.INFO):
        async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
            await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
            await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1]})
    assert secret_market_payload not in caplog.text


@pytest.mark.asyncio
async def test_non_allowlisted_route_is_rejected_before_transport() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return response({})

    transport = httpx.MockTransport(handler)
    async with KeylessHttpClient(_transport=transport) as client:
        for route in (
            "/v1/../private",
            "/v1/%2e%2e/private",
            "https://evil.example/v1/cryptocurrency/map",
            f"{ROUTES['cmc_quotes_latest']}?ids=1",
            f"{ROUTES['cmc_quotes_latest']}/",
        ):
            with pytest.raises(CmcClientError) as caught:
                await client.get(route)
            assert caught.value.code is ErrorCode.INVALID_ARGUMENT
    assert not called


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [0, 0.0, "0", " 0 "])
async def test_numeric_and_string_zero_are_success(error_code) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": error_code}, "data": []})

    assert (await run_client(handler))["data"] == []


@pytest.mark.asyncio
async def test_application_error_is_not_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response(
            {"status": {"error_code": 1006, "error_message": "bad request"}, "data": None}
        )

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_APPLICATION_ERROR
    assert caught.value.provider_error_code == 1006


@pytest.mark.asyncio
async def test_invalid_provider_error_code_is_contract_mismatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": None}, "data": []})

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": {}},
        {"status": {"notice": "missing code"}, "data": []},
        {"status": {"error_code": False}, "data": []},
        {"status": {"error_code": 0}},
    ],
)
async def test_malformed_envelopes_are_rejected(payload) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response(payload)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
async def test_malformed_json_is_contract_mismatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
async def test_429_retries_then_succeeds_and_honors_retry_after() -> None:
    attempts = 0
    sleeps = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return response({}, 429, {"Retry-After": "0.25"})
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    result = await run_client(handler, _sleep=record_sleep)
    assert result["data"] == {"ok": True}
    assert attempts == 2
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_429_exhaustion_is_rate_limited() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response({}, 429)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler, _sleep=lambda delay: _immediate())
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert caught.value.attempts == 3
    assert attempts == 3


def test_retry_after_zero_and_exact_cap_are_accepted() -> None:
    assert _retry_after_seconds("0", 2.0) == 0.0
    assert _retry_after_seconds("2", 2.0) == 2.0
    assert _retry_after_seconds("2.001", 2.0) is None


def test_retry_after_http_date_is_parsed_as_a_bounded_delay() -> None:
    retry_at = datetime.now(UTC) + timedelta(minutes=1)
    header = format_datetime(retry_at, usegmt=True)
    delay = _retry_after_seconds(header, 120.0)
    assert delay is not None
    assert 0.0 < delay <= 60.0


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [502, 503, 504])
async def test_selected_5xx_retries_then_succeeds(status_code: int) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return response({}, status_code)
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    result = await run_client(handler, _sleep=lambda delay: _immediate())
    assert result["data"] == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["http", "network"])
async def test_transient_retries_use_capped_exponential_jitter(failure_kind: str) -> None:
    attempts = 0
    random_ranges = []
    sleeps = []

    def choose_upper_bound(lower: float, upper: float) -> float:
        random_ranges.append((lower, upper))
        return upper

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            if failure_kind == "network":
                raise httpx.ConnectError("network", request=request)
            return response({}, 502)
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler),
        max_attempts=4,
        backoff_base_seconds=0.25,
        backoff_max_seconds=0.75,
        _random_uniform=choose_upper_bound,
        _sleep=record_sleep,
    ) as client:
        assert (await client.get(ROUTES["cmc_quotes_latest"]))["data"] == {"ok": True}

    assert attempts == 4
    assert random_ranges == [(0.0, 0.25), (0.0, 0.5), (0.0, 0.75)]
    assert sleeps == [0.25, 0.5, 0.75]


@pytest.mark.asyncio
async def test_http_500_is_classified_as_5xx_without_retry() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response({}, 500)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_5XX
    assert caught.value.attempts == 1
    assert attempts == 1


@pytest.mark.asyncio
async def test_response_exactly_at_size_limit_is_accepted() -> None:
    content = b'{"status":{"error_code":0},"data":[]}'

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), max_response_bytes=len(content)
    ) as client:
        assert (await client.get(ROUTES["cmc_quotes_latest"]))["data"] == []


@pytest.mark.asyncio
async def test_deterministic_400_is_not_retried() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response({}, 400)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_HTTP_ERROR
    assert caught.value.attempts == 1
    assert attempts == 1


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_classified() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler, _sleep=lambda delay: _immediate())
    assert caught.value.code is ErrorCode.UPSTREAM_TIMEOUT
    assert caught.value.attempts == 3
    assert attempts == 3


async def _immediate() -> None:
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            b'{"status":{"error_code":400,"error_message":"Invalid value for \\"id\\": \\"x\\""}}',
            'CoinMarketCap returned HTTP 400: Invalid value for "id": "x"',
        ),
        (b'{"error_message":"bad\\r\\ninput"}', "CoinMarketCap returned HTTP 400: bad input"),
        (b"<html>not json</html>", "CoinMarketCap returned HTTP 400"),
        (b'{"status":{"error_message":"' + b"x" * 5000 + b'"}}', "CoinMarketCap returned HTTP 400"),
    ],
)
async def test_non_retryable_4xx_surfaces_a_bounded_provider_reason(
    body: bytes, expected: str
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, content=body)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_HTTP_ERROR
    assert caught.value.message == expected
    assert calls == 1


@pytest.mark.asyncio
async def test_slow_drip_body_hits_the_wall_clock_deadline() -> None:
    class Drip(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b" "

    with pytest.raises(CmcClientError) as caught:
        await run_client(
            lambda request: httpx.Response(200, stream=Drip()),
            request_deadline_seconds=0.05,
            max_attempts=2,
            _sleep=lambda delay: asyncio.sleep(0),
        )
    assert caught.value.code is ErrorCode.UPSTREAM_TIMEOUT
    assert caught.value.attempts == 2


def test_request_deadline_must_be_positive_and_finite() -> None:
    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            KeylessHttpClient(request_deadline_seconds=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["zlib", "raw", "multi-gzip"])
async def test_deflate_variants_and_multi_member_gzip_decode(variant: str) -> None:
    import gzip
    import json
    import zlib

    payload = {"status": {"error_code": 0}, "data": {"items": list(range(50))}}
    raw = json.dumps(payload).encode()
    if variant == "zlib":
        body, encoding = zlib.compress(raw), "deflate"
    elif variant == "raw":
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        body, encoding = compressor.compress(raw) + compressor.flush(), "deflate"
    else:
        body, encoding = gzip.compress(raw[:20]) + gzip.compress(raw[20:]), "gzip"

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(0, len(body), 7):  # Split headers and members across chunks.
                yield body[index : index + 7]

    result = await run_client(
        lambda request: httpx.Response(200, stream=Chunks(), headers={"Content-Encoding": encoding})
    )
    assert result == payload


@pytest.mark.asyncio
async def test_call_metadata_is_isolated_per_concurrent_call() -> None:
    first_seen = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["id"] == "slow" and not first_seen.is_set():
            first_seen.set()
            return httpx.Response(503)
        await first_seen.wait()
        return response({"status": {"error_code": 0}, "data": {}})

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler),
        cache_enabled=False,
        _sleep=lambda d: asyncio.sleep(0),
    ) as client:
        route = ROUTES["cmc_quotes_latest"]

        async def call(ident: str) -> tuple[int, int | None]:
            await client.get(route, {"id": ident})
            return client._last_attempts, client._last_status_code

        assert await asyncio.gather(call("slow"), call("fast")) == [(2, 200), (1, 200)]

from __future__ import annotations

import httpx
import pytest

from coinmarketcap_keyless_mcp.client import KeylessHttpClient
from coinmarketcap_keyless_mcp.contracts import ROUTES
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode

FAMILY_FIXTURES = {
    "identity_info": {
        "status": {"error_code": 0, "timestamp": "2026-01-01T00:00:00Z"},
        "data": {"1": {"id": 1, "name": "Bitcoin", "urls": {"website": []}}},
    },
    "quotes_listings": {
        "status": {"error_code": "0", "elapsed": 1, "credit_count": 1},
        "data": [{"id": 1, "quote": {"USD": {"price": 123.45, "percent_change_24h": None}}}],
    },
    "global_metrics": {
        "status": {"error_code": 0, "notice": None},
        "data": {"quote": {"USD": {"total_market_cap": 1.0, "market_cap_change_24h": -2.5}}},
    },
    "sentiment_breadth": {
        "status": {"error_code": 0},
        "data": [],
    },
    "indices": {
        "status": {"error_code": 0, "last_updated": "2026-01-01T00:00:00Z"},
        "data": {"values": [{"timestamp": "1700000000", "value": 100.25}], "constituents": []},
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", FAMILY_FIXTURES.values())
async def test_valid_provider_envelopes_are_preserved(fixture: dict) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        result = await client.get(ROUTES["cmc_quotes_latest"])

    assert result == fixture


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture",
    [
        {},
        {"status": {}},
        {"status": {"error_code": 0}},
        {"status": {"error_code": None}, "data": []},
    ],
)
async def test_malformed_provider_envelopes_are_rejected(fixture: dict) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTES["cmc_global_metrics_latest"])
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


# --- v1.1 E1-R routes through the real client boundary --------------------------------

import json  # noqa: E402

from mcp import Client  # noqa: E402

from coinmarketcap_keyless_mcp.server import create_server  # noqa: E402

E1R_CALLS = {
    "cmc_simple_price": ({"ids": [1]}, {"id": "1", "convert": "USD"}),
    "cmc_crypto_categories": ({}, {"start": "1", "limit": "100"}),
    "cmc_crypto_category": (
        {"id": "605eAB"},
        {"id": "605eAB", "start": "1", "limit": "100", "convert": "USD"},
    ),
    "cmc_price_conversion": (
        {"amount": 1e-8, "symbol": "btc"},
        {"amount": "0.00000001", "symbol": "btc", "convert": "USD"},
    ),
    "cmc_exchange_map": (
        {},
        {"listing_status": "active", "start": "1", "limit": "100", "sort": "id"},
    ),
}
E1R_ENVELOPE = {
    "status": {"error_code": 0, "notice": None, "credit_count": 1},
    "data": {"1": {"id": "605e", "coins": [], "price": 1.5e-9, "change": -0.0}},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", list(E1R_CALLS))
async def test_e1r_wire_query_and_unchanged_envelope(tool: str) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=E1R_ENVELOPE)

    arguments, query = E1R_CALLS[tool]
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(tool, arguments)
            second = await client.call_tool(tool, arguments)  # served from the TTL cache
    assert not first.is_error and not second.is_error
    assert first.structured_content == second.structured_content == E1R_ENVELOPE
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/public-api" + ROUTES[tool]
    assert dict(request.url.params) == query
    assert "x-cmc_pro_api_key" not in request.headers
    assert "authorization" not in request.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", list(E1R_CALLS))
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(429), ErrorCode.RATE_LIMITED),
        (
            httpx.Response(
                200, json={"status": {"error_code": 400, "error_message": "bad"}, "data": None}
            ),
            ErrorCode.UPSTREAM_APPLICATION_ERROR,
        ),
        (
            httpx.Response(200, json={"status": {"error_code": 0}}),
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
        ),
        (httpx.Response(200, content=b"not json"), ErrorCode.UPSTREAM_CONTRACT_MISMATCH),
        (
            httpx.Response(
                200,
                content=json.dumps(
                    {"status": {"error_code": 0}, "data": "x" * (2 * 1024 * 1024)}
                ).encode(),
            ),
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
        ),
    ],
)
async def test_e1r_failures_keep_the_stable_taxonomy_and_are_not_cached(
    tool: str, response: httpx.Response, code: ErrorCode
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    arguments, _ = E1R_CALLS[tool]
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), max_attempts=1
    ) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(tool, arguments)
            second = await client.call_tool(tool, arguments)
    assert first.is_error and second.is_error
    assert first.content[0].text.startswith(f"Error executing tool {tool}: {code.value}:")
    assert calls == 2


# --- v1.1 E2-A routes through the real client boundary --------------------------------

E2A_CALLS = {
    "cmc_dex_platform_list": ({}, {}),
    "cmc_dex_token_price": (
        {"platform": "eThereum", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
        {"platform": "eThereum", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
    ),
}
E2A_ENVELOPE = {
    "status": {"error_code": "0", "credit_count": 0},
    "data": {"p": 0.99981234, "pid": 1, "n": "B² Network", "extra": [None, -0.0]},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", list(E2A_CALLS))
async def test_e2a_wire_query_unchanged_envelope_and_cache_hit(tool: str) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=E2A_ENVELOPE)

    arguments, query = E2A_CALLS[tool]
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(tool, arguments)
            second = await client.call_tool(tool, arguments)
    assert not first.is_error and not second.is_error
    assert first.structured_content == second.structured_content == E2A_ENVELOPE
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).startswith("https://pro-api.coinmarketcap.com/public-api/")
    assert request.url.path == "/public-api" + ROUTES[tool]
    assert dict(request.url.params) == query
    assert "x-cmc_pro_api_key" not in request.headers
    assert "authorization" not in request.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", list(E2A_CALLS))
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(400), ErrorCode.UPSTREAM_HTTP_ERROR),
        (httpx.Response(429), ErrorCode.RATE_LIMITED),
        (
            httpx.Response(
                200, json={"status": {"error_code": 400, "error_message": "bad"}, "data": None}
            ),
            ErrorCode.UPSTREAM_APPLICATION_ERROR,
        ),
        (
            httpx.Response(200, json={"status": {"error_code": 0}}),
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
        ),
        (
            httpx.Response(
                200,
                content=json.dumps(
                    {"status": {"error_code": 0}, "data": "x" * (2 * 1024 * 1024)}
                ).encode(),
            ),
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
        ),
    ],
)
async def test_e2a_failures_keep_the_stable_taxonomy_and_are_not_cached(
    tool: str, response: httpx.Response, code: ErrorCode
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    arguments, _ = E2A_CALLS[tool]
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), max_attempts=1
    ) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(tool, arguments)
            second = await client.call_tool(tool, arguments)
    assert first.is_error and second.is_error
    assert first.content[0].text.startswith(f"Error executing tool {tool}: {code.value}:")
    assert calls == 2

"""v1.1 E2-D D16 ``cmc_dex_holders_count`` (verification/v1.1-e2d-contract-review.md)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from mcp import Client

from coinmarketcap_keyless_mcp import server as server_module
from coinmarketcap_keyless_mcp.client import CACHE_TTLS_BY_ROUTE, KeylessHttpClient
from coinmarketcap_keyless_mcp.contracts import ROUTES, TOOL_CONTRACTS
from coinmarketcap_keyless_mcp.errors import ErrorCode
from coinmarketcap_keyless_mcp.server import create_server

TOOL = "cmc_dex_holders_count"
ROUTE = "/v1/dex/holders/count"
DESCRIPTION = (
    "Get the CoinMarketCap DEX holder count for one token identified by platform name and "
    "token contract address; use platform-list to discover platform names."
)
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
INT64_MAX = 2**63 - 1


def _envelope(count: int) -> dict[str, Any]:
    # HolderCountVO: platformId int32, count int64, tokenAddress string.
    return {
        "status": {"error_code": "0", "error_message": "SUCCESS", "credit_count": 0},
        "data": {"platformId": 1, "count": count, "tokenAddress": USDC.lower()},
    }


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((route, params))
        return {"status": {"error_code": 0}, "data": {"count": 1}}


async def _no_sleep(_: float) -> None:
    return None


# --- contract identity ---------------------------------------------------------------


def test_d16_contract_identity_route_and_ttl() -> None:
    (contract,) = [c for c in TOOL_CONTRACTS if c.name == TOOL]
    assert (contract.name, contract.route, contract.method) == (TOOL, ROUTE, "GET")
    assert contract.description == DESCRIPTION
    assert [c.route for c in TOOL_CONTRACTS].count(ROUTE) == 1
    assert len(TOOL_CONTRACTS) == 23
    assert TOOL_CONTRACTS[-1] is contract
    assert ROUTES[TOOL] == ROUTE
    assert CACHE_TTLS_BY_ROUTE[ROUTE] == 60


@pytest.mark.asyncio
async def test_d16_schema_is_strict_required_and_fragments_equal_d3_d4() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    schema = tools[TOOL].input_schema
    assert tools[TOOL].description == DESCRIPTION
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["platform", "address"]
    assert list(schema["properties"]) == ["platform", "address"]
    for other in ("cmc_dex_token", "cmc_dex_token_price"):
        assert schema["properties"] == tools[other].input_schema["properties"]
    assert "default" not in json.dumps(schema)


# --- serialization -------------------------------------------------------------------

ACCEPTED = [
    ("Ethereum", USDC),
    ("ethereum", USDC.lower()),
    ("B² Network", "0xAbCdEf"),
    ("x" * 64, "a" * 128),
    ("solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
    ("Sui", "0x2::sui::SUI"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("platform", "address"), ACCEPTED)
async def test_d16_serializes_exactly_platform_then_token_address(
    platform: str, address: str
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": platform, "address": address})
    assert not result.is_error
    ((route, params),) = recording.calls
    assert route == ROUTE
    assert params == {"platform": platform, "tokenAddress": address}
    assert list(params) == ["platform", "tokenAddress"]


@pytest.mark.asyncio
async def test_d16_handler_delegates_only_to_dex_holders_count_params(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def spy(platform: str, address: str) -> dict[str, str]:
        seen.append((platform, address))
        return {"platform": platform, "tokenAddress": address}

    def forbidden(*args: Any) -> dict[str, str]:
        raise AssertionError("D16 must not use another route's query helper")

    monkeypatch.setattr(server_module, "dex_holders_count_params", spy)
    monkeypatch.setattr(server_module, "dex_token_params", forbidden)
    monkeypatch.setattr(server_module, "dex_token_price_params", forbidden)
    monkeypatch.setattr(server_module, "dex_platform_detail_params", forbidden)
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": "Plat", "address": "Addr"})
    assert not result.is_error
    assert seen == [("Plat", "Addr")]  # not swapped
    assert recording.calls == [(ROUTE, {"platform": "Plat", "tokenAddress": "Addr"})]


# --- validation before network -------------------------------------------------------

OK = {"platform": "Ethereum", "address": USDC}

INVALID = [
    {},
    {"platform": "Ethereum"},
    {"address": USDC},
    {"platform": "Ethereum", "tokenAddress": USDC},
    {"platform": "Ethereum", "token_address": USDC},
    {**OK, "tokenAddress": USDC},
    {**OK, "token_address": USDC},
    {**OK, "tag": "x"},
    {**OK, "platformId": 1},
    {**OK, "platform": ""},
    {**OK, "address": ""},
    {**OK, "platform": "x" * 65},
    {**OK, "address": "a" * 129},
    {**OK, "platform": " Ethereum"},
    {**OK, "platform": "Ethereum "},
    {**OK, "address": " " + USDC},
    {**OK, "address": USDC + " "},
    {**OK, "platform": "Eth\nereum"},
    {**OK, "platform": "Eth\x00ereum"},
    {**OK, "platform": "Eth\x7fereum"},
    {**OK, "address": "0xA0\tb8"},
    {**OK, "platform": "Ethereum&platform=x"},
    {**OK, "platform": "Ethereum=1"},
    {**OK, "platform": "Ethereum?x"},
    {**OK, "platform": "Ethereum#x"},
    {**OK, "address": "0xA0/b8"},
    {**OK, "address": "0xA0 b8"},
    {**OK, "address": "0xA0%20b8"},
    {**OK, "address": "0xA0&b8"},
    {**OK, "platform": 1},
    {**OK, "platform": None},
    {**OK, "address": 1},
    {**OK, "address": ["0xA0b8"]},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", INVALID)
async def test_d16_invalid_arguments_are_rejected_with_zero_transport_calls(
    arguments: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_envelope(1))

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, arguments)
    assert result.is_error
    assert requests == []


# --- wire, envelope and cache through the real client --------------------------------


async def _wire(platform: str, address: str) -> httpx.Request:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_envelope(1))

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, {"platform": platform, "address": address})
    assert not result.is_error
    (request,) = requests
    return request


@pytest.mark.asyncio
async def test_d16_wire_request_is_keyless_get_with_platform_and_token_address() -> None:
    request = await _wire("Ethereum", USDC)
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "pro-api.coinmarketcap.com"
    assert request.url.path == "/public-api/v1/dex/holders/count"
    assert request.url.query == f"platform=Ethereum&tokenAddress={USDC}".encode()
    assert list(request.url.params.multi_items()) == [
        ("platform", "Ethereum"),
        ("tokenAddress", USDC),
    ]
    assert b"&address=" not in request.url.query
    assert not request.url.query.startswith(b"address=")
    assert request.content == b""
    assert "x-cmc_pro_api_key" not in request.headers
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


@pytest.mark.asyncio
async def test_d16_case_and_non_ascii_are_sent_unchanged() -> None:
    request = await _wire("eThErEuM", "0xAbCdEf")
    assert request.url.query == b"platform=eThErEuM&tokenAddress=0xAbCdEf"
    request = await _wire("B² Network", "0xabc")
    assert request.url.params["platform"] == "B² Network"
    assert request.url.query == b"platform=B%C2%B2+Network&tokenAddress=0xabc"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, INT64_MAX])
async def test_d16_provider_envelope_and_holder_count_are_preserved_verbatim(count: int) -> None:
    envelope = _envelope(count)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, OK)
    assert not result.is_error
    assert result.structured_content == envelope
    assert json.dumps(result.structured_content, sort_keys=True) == json.dumps(
        envelope, sort_keys=True
    )
    data = result.structured_content["data"]
    assert data["count"] == count and type(data["count"]) is int
    assert data["tokenAddress"] == USDC.lower()  # echo is not normalized to the request


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_d16_success_is_cached_for_exactly_60_seconds() -> None:
    clock = Clock()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": {"count": calls}})

    params = {"platform": "Ethereum", "tokenAddress": USDC}
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _monotonic=clock
    ) as client:
        assert (await client.get(ROUTE, params))["data"]["count"] == 1
        clock.value = 59.99
        assert (await client.get(ROUTE, params))["data"]["count"] == 1
        clock.value = 60
        assert (await client.get(ROUTE, params))["data"]["count"] == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_d16_cache_keys_are_case_distinct_and_independent_of_d3_d4() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": {"count": 1}})

    variants = [
        (TOOL, {"platform": "Ethereum", "address": USDC}),
        (TOOL, {"platform": "ethereum", "address": USDC}),
        (TOOL, {"platform": "Ethereum", "address": USDC.lower()}),
        ("cmc_dex_token", {"platform": "Ethereum", "address": USDC}),
        ("cmc_dex_token_price", {"platform": "Ethereum", "address": USDC}),
    ]
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            for tool, arguments in variants:
                assert not (await client.call_tool(tool, arguments)).is_error
            for tool, arguments in variants:  # every second call is a cache hit
                assert not (await client.call_tool(tool, arguments)).is_error
    assert len(requests) == len(variants)
    paths = [r.url.path for r in requests]
    assert paths.count("/public-api/v1/dex/holders/count") == 3
    assert paths.count("/public-api/v1/dex/token") == 1
    assert paths.count("/public-api/v1/dex/token/price") == 1


# --- error taxonomy ------------------------------------------------------------------

OVERSIZE = json.dumps({"status": {"error_code": 0}, "data": "x" * (2 * 1024 * 1024)}).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("make_response", "code", "attempts"),
    [
        (lambda: httpx.ReadTimeout("slow"), ErrorCode.UPSTREAM_TIMEOUT, 3),
        (lambda: httpx.ConnectError("down"), ErrorCode.UPSTREAM_NETWORK_ERROR, 3),
        (lambda: httpx.Response(429), ErrorCode.RATE_LIMITED, 3),
        (lambda: httpx.Response(502), ErrorCode.UPSTREAM_5XX, 3),
        (lambda: httpx.Response(503), ErrorCode.UPSTREAM_5XX, 3),
        (lambda: httpx.Response(504), ErrorCode.UPSTREAM_5XX, 3),
        (lambda: httpx.Response(500), ErrorCode.UPSTREAM_5XX, 1),
        (lambda: httpx.Response(400), ErrorCode.UPSTREAM_HTTP_ERROR, 1),
        (lambda: httpx.Response(404), ErrorCode.UPSTREAM_HTTP_ERROR, 1),
        (
            lambda: httpx.Response(
                200, json={"status": {"error_code": 400, "error_message": "bad"}, "data": None}
            ),
            ErrorCode.UPSTREAM_APPLICATION_ERROR,
            1,
        ),
        (
            lambda: httpx.Response(200, json={"status": {"error_code": 0}}),
            ErrorCode.UPSTREAM_CONTRACT_MISMATCH,
            1,
        ),
        (lambda: httpx.Response(200, content=b"not json"), ErrorCode.UPSTREAM_CONTRACT_MISMATCH, 1),
        (lambda: httpx.Response(200, content=OVERSIZE), ErrorCode.UPSTREAM_CONTRACT_MISMATCH, 1),
    ],
)
async def test_d16_failures_map_exactly_and_are_not_cached(make_response, code, attempts) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        outcome = make_response()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _sleep=_no_sleep
    ) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(TOOL, OK)
            assert calls == attempts
            second = await client.call_tool(TOOL, OK)
    for result in (first, second):
        assert result.is_error
        text = result.content[0].text
        assert text.startswith(f"Error executing tool {TOOL}: {code.value}:")
        assert ErrorCode.UNSUPPORTED_ROUTE.value not in text
        assert ErrorCode.INTERNAL_ERROR.value not in text
    assert calls == 2 * attempts

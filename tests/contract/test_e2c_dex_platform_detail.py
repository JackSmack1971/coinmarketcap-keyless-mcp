"""v1.1 E2-C D12 ``cmc_dex_platform_detail`` (verification/v1.1-e2c-contract-review.md)."""

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

TOOL = "cmc_dex_platform_detail"
ROUTE = "/v1/dex/platform/detail"
DESCRIPTION = (
    "Get CoinMarketCap DEX detail for one blockchain platform identified by platform name; "
    "use platform-list to discover platform names."
)
D4_PROPERTIES_TOOL = "cmc_dex_token_price"

# Realistic PlatformDTO: string dn, booleans, int32 fields, URL templates.
PLATFORM_DETAIL_ENVELOPE = {
    "status": {"error_code": "0", "error_message": "SUCCESS", "credit_count": 0},
    "data": {
        "id": 1,
        "n": "Ethereum",
        "i": "https://cdn.example.com/icons/eth.png",
        "uf": "https://etherscan.io/token/{tokenAddress}",
        "dn": "12",
        "txuf": "https://etherscan.io/tx/{txHash}",
        "v": True,
        "p": False,
        "addrUrl": "https://etherscan.io/address/{address}",
        "chId": 1,
        "puf": "https://dexscan.io/pool/{poolAddress}",
        "wcId": 2001,
        "hl": 1,
        "ho": 3,
        "pltA": "ETH",
        "cid": 0,
        "extra": [None, "B² Network", 1.50],
    },
}


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((route, params))
        return {"status": {"error_code": 0}, "data": {"id": 1, "n": "x"}}


async def _no_sleep(_: float) -> None:
    return None


# --- contract identity ---------------------------------------------------------------


def test_d12_contract_identity_route_and_ttl() -> None:
    (contract,) = [c for c in TOOL_CONTRACTS if c.name == TOOL]
    assert (contract.name, contract.route, contract.method) == (TOOL, ROUTE, "GET")
    assert contract.description == DESCRIPTION
    assert [c.route for c in TOOL_CONTRACTS].count(ROUTE) == 1
    assert len(TOOL_CONTRACTS) == 22
    assert TOOL_CONTRACTS[-1] is contract
    assert ROUTES[TOOL] == ROUTE
    assert CACHE_TTLS_BY_ROUTE[ROUTE] == 900


@pytest.mark.asyncio
async def test_d12_schema_is_strict_required_and_platform_fragment_equals_d3_d4() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    schema = tools[TOOL].input_schema
    assert tools[TOOL].description == DESCRIPTION
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["platform"]
    assert list(schema["properties"]) == ["platform"]
    for other in (D4_PROPERTIES_TOOL, "cmc_dex_token"):
        assert (
            schema["properties"]["platform"] == tools[other].input_schema["properties"]["platform"]
        )
    assert "default" not in json.dumps(schema)


# --- serialization -------------------------------------------------------------------

ACCEPTED = ["Ethereum", "eThErEuM", "BNB Smart Chain (BEP20)", "B² Network", "x" * 64, "1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ACCEPTED)
async def test_d12_serializes_exactly_platform_name(platform: str) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": platform})
    assert not result.is_error
    assert recording.calls == [(ROUTE, {"platformName": platform})]


@pytest.mark.asyncio
async def test_d12_handler_delegates_only_to_dex_platform_detail_params(monkeypatch) -> None:
    seen: list[str] = []

    def spy(platform: str) -> dict[str, str]:
        seen.append(platform)
        return {"platformName": platform}

    def forbidden(*args: Any) -> dict[str, str]:
        raise AssertionError("D12 must not use a token query helper")

    monkeypatch.setattr(server_module, "dex_platform_detail_params", spy)
    monkeypatch.setattr(server_module, "dex_token_params", forbidden)
    monkeypatch.setattr(server_module, "dex_token_price_params", forbidden)
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": "Plat"})
    assert not result.is_error
    assert seen == ["Plat"]
    assert recording.calls == [(ROUTE, {"platformName": "Plat"})]


# --- validation before network -------------------------------------------------------

INVALID = [
    {},
    {"platformName": "Ethereum"},
    {"platform_name": "Ethereum"},
    {"id": 1},
    {"platform": "Ethereum", "platformName": "Ethereum"},
    {"platform": "Ethereum", "platform_name": "Ethereum"},
    {"platform": "Ethereum", "id": 1},
    {"platform": "Ethereum", "address": "0xA0b8"},
    {"platform": ""},
    {"platform": "x" * 65},
    {"platform": " Ethereum"},
    {"platform": "Ethereum "},
    {"platform": " "},
    {"platform": "Ethereum\n"},
    {"platform": "Eth\tereum"},
    {"platform": "Eth\x00ereum"},
    {"platform": "Eth\x7fereum"},
    {"platform": "Eth\x85ereum"},
    {"platform": "Ethereum&platform=x"},
    {"platform": "Ethereum=1"},
    {"platform": "Ethereum?x"},
    {"platform": "Ethereum#x"},
    {"platform": 1},
    {"platform": None},
    {"platform": ["Ethereum"]},
    {"platform": {"n": "Ethereum"}},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", INVALID)
async def test_d12_invalid_arguments_are_rejected_with_zero_transport_calls(
    arguments: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=PLATFORM_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, arguments)
    assert result.is_error
    assert requests == []


# --- wire, envelope and cache through the real client --------------------------------


async def _wire(platform: str) -> httpx.Request:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=PLATFORM_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, {"platform": platform})
    assert not result.is_error
    (request,) = requests
    return request


@pytest.mark.asyncio
async def test_d12_wire_request_is_keyless_get_with_only_platform_name() -> None:
    request = await _wire("BNB Smart Chain (BEP20)")
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "pro-api.coinmarketcap.com"
    assert request.url.path == "/public-api/v1/dex/platform/detail"
    assert request.url.query == b"platformName=BNB+Smart+Chain+%28BEP20%29"
    assert list(request.url.params.multi_items()) == [("platformName", "BNB Smart Chain (BEP20)")]
    assert b"platform=" not in request.url.query
    assert b"platform_name=" not in request.url.query
    assert "x-cmc_pro_api_key" not in request.headers
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


@pytest.mark.asyncio
async def test_d12_case_and_non_ascii_are_sent_unchanged() -> None:
    assert (await _wire("eThErEuM")).url.query == b"platformName=eThErEuM"
    request = await _wire("B² Network")
    assert request.url.params["platformName"] == "B² Network"
    assert request.url.query == b"platformName=B%C2%B2+Network"


@pytest.mark.asyncio
async def test_d12_provider_envelope_and_platform_dto_are_preserved_verbatim() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PLATFORM_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, {"platform": "Ethereum"})
    assert not result.is_error
    assert result.structured_content == PLATFORM_DETAIL_ENVELOPE
    data = result.structured_content["data"]
    assert data["dn"] == "12"  # string DEX count is never coerced
    assert data["v"] is True and data["p"] is False


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_d12_success_is_cached_for_exactly_900_seconds() -> None:
    clock = Clock()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": {"call": calls}})

    params = {"platformName": "Ethereum"}
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _monotonic=clock
    ) as client:
        assert (await client.get(ROUTE, params))["data"]["call"] == 1
        clock.value = 899.99
        assert (await client.get(ROUTE, params))["data"]["call"] == 1
        clock.value = 900
        assert (await client.get(ROUTE, params))["data"]["call"] == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_d12_cache_keys_are_case_distinct_and_independent_of_d11_d3_d4() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": {"id": 1, "n": "x"}})

    address = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    variants = [
        (TOOL, {"platform": "Ethereum"}),
        (TOOL, {"platform": "ethereum"}),
        (TOOL, {"platform": "Solana"}),
        ("cmc_dex_platform_list", {}),
        ("cmc_dex_token", {"platform": "Ethereum", "address": address}),
        (D4_PROPERTIES_TOOL, {"platform": "Ethereum", "address": address}),
    ]
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            for tool, arguments in variants:
                assert not (await client.call_tool(tool, arguments)).is_error
            for tool, arguments in variants:  # every second call is a cache hit
                assert not (await client.call_tool(tool, arguments)).is_error
    assert len(requests) == len(variants)
    paths = [r.url.path for r in requests]
    assert paths.count("/public-api/v1/dex/platform/detail") == 3
    assert paths.count("/public-api/v1/dex/platform/list") == 1
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
async def test_d12_failures_map_exactly_and_are_not_cached(make_response, code, attempts) -> None:
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
            first = await client.call_tool(TOOL, {"platform": "Ethereum"})
            assert calls == attempts
            second = await client.call_tool(TOOL, {"platform": "Ethereum"})
    for result in (first, second):
        assert result.is_error
        text = result.content[0].text
        assert text.startswith(f"Error executing tool {TOOL}: {code.value}:")
        assert ErrorCode.UNSUPPORTED_ROUTE.value not in text
        assert ErrorCode.INTERNAL_ERROR.value not in text
    assert calls == 2 * attempts

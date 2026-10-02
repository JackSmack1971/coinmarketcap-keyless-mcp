"""v1.1 E2-B D3 ``cmc_dex_token`` (verification/v1.1-e2b-contract-review.md)."""

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

TOOL = "cmc_dex_token"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
DESCRIPTION = (
    "Get CoinMarketCap DEX token detail (metadata, market, liquidity and pool fields) for one "
    "token identified by platform name and token contract address; use platform-list to "
    "discover platform names."
)

# Realistic TokenDetailDTO shape: string market values, nested pools/stats/cexs/sig.
TOKEN_DETAIL_ENVELOPE = {
    "status": {"error_code": "0", "error_message": "SUCCESS", "credit_count": 0},
    "data": {
        "n": "USD Coin",
        "sym": "USDC",
        "addr": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "plt": "ethereum",
        "pdex": "ethereum",
        "pcid": 1027,
        "pid": 1,
        "dec": 6,
        "crt": None,
        "pubAt": 1533324504000,
        "fdv": "51234567890.123456789",
        "mcap": "51234567890.12",
        "ts": "51234567890.000001",
        "liqUsd": "123456789.000000000001",
        "liq": "0",
        "hld": 2345678,
        "p": "0.99981234000000000001",
        "ph24h": "1.0001",
        "pl24h": "0.9997",
        "pt": 1790000000000,
        "bcr": 0,
        "sts": [{"tp": "24h", "vu": "123456.789", "txs": 1024, "pc": -0.0}],
        "pls": [
            {
                "addr": "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
                "v24": "98765.4321",
                "t0": {"addr": USDC, "sym": "USDC", "liqUsd": "1"},
                "t1": {"addr": "0xC02a", "sym": "WETH", "liqUsd": "2"},
                "top": True,
                "mi": False,
            }
        ],
        "cexs": [{"id": 270, "slug": "binance", "n": "Binance", "cat": ["spot"]}],
        "sig": {"mtp": 0, "psc": 0},
        "nps": 1,
        "rl": None,
        "extra": [None, "B² Network"],
    },
}

D4_PROPERTIES_TOOL = "cmc_dex_token_price"


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((route, params))
        return {"status": {"error_code": 0}, "data": {"addr": "x"}}


async def _no_sleep(_: float) -> None:
    return None


# --- contract identity ---------------------------------------------------------------


def test_d3_contract_identity_route_and_ttl() -> None:
    contract = TOOL_CONTRACTS[-1]
    assert (contract.name, contract.route, contract.method) == (TOOL, "/v1/dex/token", "GET")
    assert contract.description == DESCRIPTION
    assert [c.route for c in TOOL_CONTRACTS].count("/v1/dex/token") == 1
    assert len(TOOL_CONTRACTS) == 21
    assert CACHE_TTLS_BY_ROUTE["/v1/dex/token"] == 15


@pytest.mark.asyncio
async def test_d3_schema_is_strict_and_property_fragments_equal_d4() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    schema = tools[TOOL].input_schema
    d4 = tools[D4_PROPERTIES_TOOL].input_schema
    assert tools[TOOL].description == DESCRIPTION
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["platform", "address"]
    assert list(schema["properties"]) == ["platform", "address"]
    assert schema["properties"] == d4["properties"]
    assert schema == {**d4, "title": "cmc_dex_tokenArguments"}
    assert "default" not in json.dumps(schema)


# --- serialization -------------------------------------------------------------------

ACCEPTED = [
    ({"platform": "Ethereum", "address": USDC}),
    ({"platform": "eThErEuM", "address": "0xa0B86991C6218B36"}),
    ({"platform": "BNB Smart Chain (BEP20)", "address": "So1111111111111111111"}),
    ({"platform": "B² Network", "address": "EQ:abc_d.e-f"}),
    ({"platform": "x" * 64, "address": "a" * 128}),
    ({"platform": "1", "address": "a"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ACCEPTED)
async def test_d3_serializes_exactly_platform_then_address(arguments: dict[str, Any]) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, arguments)
    assert not result.is_error
    assert recording.calls == [("/v1/dex/token", arguments)]
    assert list(recording.calls[0][1] or {}) == ["platform", "address"]


@pytest.mark.asyncio
async def test_d3_handler_delegates_only_to_dex_token_params(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def spy(platform: str, address: str) -> dict[str, str]:
        seen.append((platform, address))
        return {"platform": platform, "address": address}

    def forbidden(platform: str, address: str) -> dict[str, str]:
        raise AssertionError("D3 must not use the D4 query helper")

    monkeypatch.setattr(server_module, "dex_token_params", spy)
    monkeypatch.setattr(server_module, "dex_token_price_params", forbidden)
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": "Plat", "address": "Addr"})
    assert not result.is_error
    assert seen == [("Plat", "Addr")]
    assert recording.calls == [("/v1/dex/token", {"platform": "Plat", "address": "Addr"})]


# --- validation before network -------------------------------------------------------

INVALID = [
    {},
    {"platform": "Ethereum"},
    {"address": "0xA0b8"},
    {"platform": "Ethereum", "address": "0xA0b8", "network_slug": "ethereum"},
    {"platform": "Ethereum", "address": "0xA0b8", "contract_address": "0xA0b8"},
    {"platform": "Ethereum", "address": "0xA0b8", "convert": "USD"},
    {"platform": "", "address": "a"},
    {"platform": "x" * 65, "address": "a"},
    {"platform": " Ethereum", "address": "a"},
    {"platform": "Ethereum ", "address": "a"},
    {"platform": " ", "address": "a"},
    {"platform": "Ethereum\n", "address": "a"},
    {"platform": "Eth\tereum", "address": "a"},
    {"platform": "Eth\x00ereum", "address": "a"},
    {"platform": "Eth\x7fereum", "address": "a"},
    {"platform": "Eth\x85ereum", "address": "a"},
    {"platform": "Ethereum&address=0xdead", "address": "a"},
    {"platform": "Ethereum=1", "address": "a"},
    {"platform": "Ethereum?x", "address": "a"},
    {"platform": "Ethereum#x", "address": "a"},
    {"platform": 1, "address": "a"},
    {"platform": None, "address": "a"},
    {"platform": ["Ethereum"], "address": "a"},
    {"platform": "Ethereum", "address": ""},
    {"platform": "Ethereum", "address": "a" * 129},
    {"platform": "Ethereum", "address": " 0xA0b8"},
    {"platform": "Ethereum", "address": "0xA0b8\n"},
    {"platform": "Ethereum", "address": "0xA0 b8"},
    {"platform": "Ethereum", "address": "0xA0b8&platform=x"},
    {"platform": "Ethereum", "address": "0xA0b8/../x"},
    {"platform": "Ethereum", "address": "0xA0b8?x"},
    {"platform": "Ethereum", "address": "0xA0b8#x"},
    {"platform": "Ethereum", "address": "0xA0b8%26x"},
    {"platform": "Ethereum", "address": "0xA0b8,0xC0de"},
    {"platform": "Ethereum", "address": 1},
    {"platform": "Ethereum", "address": ["0xA0b8"]},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", INVALID)
async def test_d3_invalid_arguments_are_rejected_with_zero_transport_calls(
    arguments: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=TOKEN_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, arguments)
    assert result.is_error
    assert requests == []


# --- wire, envelope and cache through the real client --------------------------------


@pytest.mark.asyncio
async def test_d3_wire_request_is_keyless_get_with_exact_encoded_query() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=TOKEN_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(
                TOOL, {"platform": "BNB Smart Chain (BEP20)", "address": "0xAbC"}
            )
    assert not result.is_error
    (request,) = requests
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "pro-api.coinmarketcap.com"
    assert request.url.path == "/public-api/v1/dex/token"
    assert request.url.query == b"platform=BNB+Smart+Chain+%28BEP20%29&address=0xAbC"
    assert list(request.url.params.multi_items()) == [
        ("platform", "BNB Smart Chain (BEP20)"),
        ("address", "0xAbC"),
    ]
    assert "x-cmc_pro_api_key" not in request.headers
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


@pytest.mark.asyncio
async def test_d3_non_ascii_platform_is_percent_encoded_unchanged() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=TOKEN_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            await client.call_tool(TOOL, {"platform": "B² Network", "address": "a"})
    assert requests[0].url.params["platform"] == "B² Network"
    assert requests[0].url.query == b"platform=B%C2%B2+Network&address=a"


@pytest.mark.asyncio
async def test_d3_provider_envelope_and_token_detail_are_preserved_verbatim() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TOKEN_DETAIL_ENVELOPE)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, {"platform": "Ethereum", "address": USDC})
    assert not result.is_error
    assert result.structured_content == TOKEN_DETAIL_ENVELOPE
    data = result.structured_content["data"]
    for key in ("p", "fdv", "mcap", "liqUsd", "ts"):
        assert isinstance(data[key], str)  # string market values are never coerced
    assert data["p"] == "0.99981234000000000001"
    assert data["pls"][0]["t1"]["sym"] == "WETH"


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_d3_success_is_cached_for_exactly_15_seconds() -> None:
    clock = Clock()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": {"call": calls}})

    params = {"platform": "Ethereum", "address": USDC}
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _monotonic=clock
    ) as client:
        assert (await client.get("/v1/dex/token", params))["data"]["call"] == 1
        clock.value = 14.99
        assert (await client.get("/v1/dex/token", params))["data"]["call"] == 1
        clock.value = 15
        assert (await client.get("/v1/dex/token", params))["data"]["call"] == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_d3_cache_keys_are_case_distinct_and_independent_of_d4() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": {"addr": "x"}})

    variants = [
        (TOOL, {"platform": "Ethereum", "address": USDC}),
        (TOOL, {"platform": "ethereum", "address": USDC}),
        (TOOL, {"platform": "Ethereum", "address": USDC.lower()}),
        (TOOL, {"platform": "Ethereum", "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7"}),
        (D4_PROPERTIES_TOOL, {"platform": "Ethereum", "address": USDC}),
    ]
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            for tool, arguments in variants:
                assert not (await client.call_tool(tool, arguments)).is_error
            for tool, arguments in variants:  # every second call is a cache hit
                assert not (await client.call_tool(tool, arguments)).is_error
    assert len(requests) == len(variants)
    assert [r.url.path for r in requests].count("/public-api/v1/dex/token") == 4
    assert [r.url.path for r in requests].count("/public-api/v1/dex/token/price") == 1


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
async def test_d3_failures_map_exactly_and_are_not_cached(make_response, code, attempts) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        outcome = make_response()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    arguments = {"platform": "Ethereum", "address": USDC}
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _sleep=_no_sleep
    ) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(TOOL, arguments)
            assert calls == attempts
            second = await client.call_tool(TOOL, arguments)
    for result in (first, second):
        assert result.is_error
        text = result.content[0].text
        assert text.startswith(f"Error executing tool {TOOL}: {code.value}:")
        assert ErrorCode.UNSUPPORTED_ROUTE.value not in text
        assert ErrorCode.INTERNAL_ERROR.value not in text
    assert calls == 2 * attempts
    assert ROUTES[TOOL] == "/v1/dex/token"

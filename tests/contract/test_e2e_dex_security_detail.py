"""v1.1 E2-E D8 ``cmc_dex_security_detail`` (verification/v1.1-e2e-contract-review.md)."""

from __future__ import annotations

import copy
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

TOOL = "cmc_dex_security_detail"
ROUTE = "/v1/dex/security/detail"
DESCRIPTION = (
    "Get CoinMarketCap DEX token security audit records for one token identified by platform "
    "name and token contract address; returns provider and third-party vendor data as-is, not a "
    "safety guarantee; use platform-list to discover platform names."
)
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

# TokenSecurityResponseDTO as documented (no field required; vendor data from GoPlus).
FULL_RECORD: dict[str, Any] = {
    "platformName": "ethereum",
    "platformId": 1,
    "tokenContractAddress": USDC.lower(),
    "securityLevel": 1,
    "categoryLevel": 0,
    "securityBatchLevel": 0,
    "extra": {
        "buyTax": "0",
        "sellTax": "0.0500",
        "isFlaggedByVendor": False,
        "isVerified": True,
        "isReported": False,
        "source": "GoPlus",
    },
    "securityItems": [
        {
            "code": "honeypot",
            "riskCode": "R002",
            "riskyLevel": 3,
            "isHit": False,
            "order": 2,
            "des": "Honeypot check",
            "groupId": 1,
        },
        {
            "code": "mintable",
            "riskCode": "R001",
            "riskyLevel": 1,
            "isHit": True,
            "order": 1,
            "des": "Mint function",
            "groupId": 1,
        },
    ],
    "evmDisplay": {"isOpenSource": "SAFE", "isProxy": "RISKY", "owner": {"nested": ["a", 1]}},
    "solanaDisplay": {},
    "exist": True,
    "tags": ["stablecoin", "Verified"],
}
SPARSE_RECORD: dict[str, Any] = {"platformName": "ethereum", "exist": False}
SECOND_RECORD: dict[str, Any] = {"platformName": "Ethereum", "securityLevel": 0, "tags": []}


def _envelope(data: Any) -> dict[str, Any]:
    return {
        "status": {"error_code": "0", "error_message": "SUCCESS", "credit_count": 0},
        "data": data,
    }


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((route, params))
        return {"status": {"error_code": 0}, "data": []}


async def _no_sleep(_: float) -> None:
    return None


# --- contract identity ---------------------------------------------------------------


def test_d8_contract_identity_route_and_ttl() -> None:
    (contract,) = [c for c in TOOL_CONTRACTS if c.name == TOOL]
    assert (contract.name, contract.route, contract.method) == (TOOL, ROUTE, "GET")
    assert contract.description == DESCRIPTION
    assert [c.route for c in TOOL_CONTRACTS].count(ROUTE) == 1
    assert len(TOOL_CONTRACTS) == 24
    assert TOOL_CONTRACTS[-1] is contract
    assert ROUTES[TOOL] == ROUTE
    assert CACHE_TTLS_BY_ROUTE[ROUTE] == 300


@pytest.mark.asyncio
async def test_d8_schema_is_strict_required_and_fragments_equal_d3_d4_d16() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    schema = tools[TOOL].input_schema
    assert tools[TOOL].description == DESCRIPTION
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["platform", "address"]
    assert list(schema["properties"]) == ["platform", "address"]
    for other in ("cmc_dex_token", "cmc_dex_token_price", "cmc_dex_holders_count"):
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
async def test_d8_serializes_exactly_platform_name_then_address(
    platform: str, address: str
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": platform, "address": address})
    assert not result.is_error
    ((route, params),) = recording.calls
    assert route == ROUTE
    assert params == {"platformName": platform, "address": address}
    assert list(params) == ["platformName", "address"]
    assert "platform" not in params


@pytest.mark.asyncio
async def test_d8_handler_delegates_only_to_dex_security_detail_params(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def spy(platform: str, address: str) -> dict[str, str]:
        seen.append((platform, address))
        return {"platformName": platform, "address": address}

    def forbidden(*args: Any) -> dict[str, str]:
        raise AssertionError("D8 must not use another route's query helper")

    monkeypatch.setattr(server_module, "dex_security_detail_params", spy)
    monkeypatch.setattr(server_module, "dex_holders_count_params", forbidden)
    monkeypatch.setattr(server_module, "dex_token_params", forbidden)
    monkeypatch.setattr(server_module, "dex_token_price_params", forbidden)
    monkeypatch.setattr(server_module, "dex_platform_detail_params", forbidden)
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(TOOL, {"platform": "Plat", "address": "Addr"})
    assert not result.is_error
    assert seen == [("Plat", "Addr")]  # not swapped
    assert recording.calls == [(ROUTE, {"platformName": "Plat", "address": "Addr"})]


# --- validation before network -------------------------------------------------------

OK = {"platform": "Ethereum", "address": USDC}

INVALID = [
    {},
    {"platform": "Ethereum"},
    {"address": USDC},
    {"platformName": "Ethereum", "address": USDC},
    {"platform_name": "Ethereum", "address": USDC},
    {"platform": "Ethereum", "tokenAddress": USDC},
    {**OK, "platformName": "Ethereum"},
    {**OK, "platform_name": "Ethereum"},
    {**OK, "size": 1},
    {**OK, "tokenAddress": USDC},
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
async def test_d8_invalid_arguments_are_rejected_with_zero_transport_calls(
    arguments: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_envelope([]))

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
        return httpx.Response(200, json=_envelope([]))

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, {"platform": platform, "address": address})
    assert not result.is_error
    (request,) = requests
    return request


@pytest.mark.asyncio
async def test_d8_wire_request_is_keyless_get_with_platform_name_and_address() -> None:
    request = await _wire("Ethereum", USDC)
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "pro-api.coinmarketcap.com"
    assert request.url.path == "/public-api/v1/dex/security/detail"
    assert request.url.query == f"platformName=Ethereum&address={USDC}".encode()
    assert list(request.url.params.multi_items()) == [
        ("platformName", "Ethereum"),
        ("address", USDC),
    ]
    assert b"platformName=" in request.url.query
    assert not request.url.query.startswith(b"platform=")
    assert b"&platform=" not in request.url.query
    assert b"tokenAddress" not in request.url.query
    assert request.content == b""
    assert "x-cmc_pro_api_key" not in request.headers
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


@pytest.mark.asyncio
async def test_d8_case_and_non_ascii_are_sent_unchanged() -> None:
    request = await _wire("eThErEuM", "0xAbCdEf")
    assert request.url.query == b"platformName=eThErEuM&address=0xAbCdEf"
    request = await _wire("B² Network", "0xabc")
    assert request.url.params["platformName"] == "B² Network"
    assert request.url.query == b"platformName=B%C2%B2+Network&address=0xabc"


PASSTHROUGH = [
    [FULL_RECORD],
    [],
    [SPARSE_RECORD],
    [FULL_RECORD, SECOND_RECORD],
    [SECOND_RECORD, FULL_RECORD],
    [{}],
    # A single object is not the documented array, but the tool adds no array check:
    # only the live verifier flags that shape.
    FULL_RECORD,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("data", PASSTHROUGH)
async def test_d8_provider_envelope_and_security_data_are_preserved_verbatim(data: Any) -> None:
    envelope = _envelope(copy.deepcopy(data))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, OK)
    assert not result.is_error
    assert result.structured_content == envelope
    assert json.dumps(result.structured_content) == json.dumps(envelope)  # order preserved
    assert result.structured_content["data"] == data


@pytest.mark.asyncio
async def test_d8_string_taxes_and_vendor_fields_are_not_coerced_or_interpreted() -> None:
    envelope = _envelope([FULL_RECORD])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            result = await client.call_tool(TOOL, OK)
    (record,) = result.structured_content["data"]
    assert record["extra"]["buyTax"] == "0" and record["extra"]["sellTax"] == "0.0500"
    assert record["extra"]["source"] == "GoPlus"
    assert [item["order"] for item in record["securityItems"]] == [2, 1]  # not reordered
    assert record["tokenContractAddress"] == USDC.lower()  # echo not normalized
    assert record["platformName"] == "ethereum"
    assert set(record) == set(FULL_RECORD)  # no verdict/score fields added


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_d8_success_is_cached_for_exactly_300_seconds() -> None:
    clock = Clock()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": [{"n": calls}]})

    params = {"platformName": "Ethereum", "address": USDC}
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _monotonic=clock
    ) as client:
        assert (await client.get(ROUTE, params))["data"] == [{"n": 1}]
        clock.value = 299.99
        assert (await client.get(ROUTE, params))["data"] == [{"n": 1}]
        clock.value = 300
        assert (await client.get(ROUTE, params))["data"] == [{"n": 2}]
    assert calls == 2


@pytest.mark.asyncio
async def test_d8_cache_keys_are_case_distinct_and_independent_of_d3_d4_d16() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": {"error_code": 0}, "data": []})

    variants = [
        (TOOL, {"platform": "Ethereum", "address": USDC}),
        (TOOL, {"platform": "ethereum", "address": USDC}),
        (TOOL, {"platform": "Ethereum", "address": USDC.lower()}),
        ("cmc_dex_token", {"platform": "Ethereum", "address": USDC}),
        ("cmc_dex_token_price", {"platform": "Ethereum", "address": USDC}),
        ("cmc_dex_holders_count", {"platform": "Ethereum", "address": USDC}),
    ]
    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            for tool, arguments in variants:
                assert not (await client.call_tool(tool, arguments)).is_error
            for tool, arguments in variants:  # every second call is a cache hit
                assert not (await client.call_tool(tool, arguments)).is_error
    assert len(requests) == len(variants)
    paths = [r.url.path for r in requests]
    assert paths.count("/public-api/v1/dex/security/detail") == 3
    assert paths.count("/public-api/v1/dex/holders/count") == 1
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
        (lambda: httpx.Response(403), ErrorCode.UPSTREAM_HTTP_ERROR, 1),
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
async def test_d8_failures_map_exactly_and_are_not_cached(make_response, code, attempts) -> None:
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


@pytest.mark.asyncio
async def test_d8_empty_array_success_is_cached() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_envelope([]))

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as upstream:
        async with Client(create_server(upstream)) as client:
            first = await client.call_tool(TOOL, OK)
            second = await client.call_tool(TOOL, OK)
    assert not first.is_error and not second.is_error
    assert first.structured_content["data"] == [] == second.structured_content["data"]
    assert calls == 1

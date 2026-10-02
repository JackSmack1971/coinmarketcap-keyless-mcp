from __future__ import annotations

from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from coinmarketcap_keyless_mcp.contracts import ROUTES, TOOL_CONTRACTS
from coinmarketcap_keyless_mcp.server import create_server


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((route, params))
        return {"status": {"error_code": 0, "notice": "fixture"}, "data": {"route": route}}


EXPECTED_NAMES = [contract.name for contract in TOOL_CONTRACTS]
CALL_ARGS = {
    "cmc_crypto_map": {"symbols": ["BTC"]},
    "cmc_crypto_info": {"ids": [1]},
    "cmc_quotes_latest": {"ids": [1], "convert": ["USD"]},
    "cmc_listings_latest": {},
    "cmc_global_metrics_latest": {},
    "cmc_fear_greed_latest": {},
    "cmc_fear_greed_historical": {},
    "cmc_altcoin_season_latest": {},
    "cmc_altcoin_season_historical": {},
    "cmc_cmc100_latest": {},
    "cmc_cmc100_historical": {},
    "cmc_cmc20_latest": {},
    "cmc_cmc20_historical": {},
    "cmc_simple_price": {"ids": [1]},
    "cmc_crypto_categories": {},
    "cmc_crypto_category": {"id": "605e2ce9d41eae1066535f7c"},
    "cmc_price_conversion": {"amount": 1, "id": 1},
    "cmc_exchange_map": {},
    "cmc_dex_platform_list": {},
    "cmc_dex_token_price": {"platform": "Ethereum", "address": "0xA0b86991"},
    "cmc_dex_token": {"platform": "Ethereum", "address": "0xA0b86991"},
    "cmc_dex_platform_detail": {"platform": "Ethereum"},
}


def _properties(server) -> dict[str, dict[str, Any]]:
    return {
        tool.name: tool.parameters["properties"] for tool in server._tool_manager._tools.values()
    }


@pytest.mark.asyncio
async def test_in_process_discovery_exposes_exact_20_tools() -> None:
    server = create_server(RecordingClient())
    async with Client(server) as client:
        discovered = await client.list_tools()
    assert [tool.name for tool in discovered.tools] == EXPECTED_NAMES
    assert [tool.description for tool in discovered.tools] == [
        contract.description for contract in TOOL_CONTRACTS
    ]
    assert all(tool.input_schema.get("additionalProperties") is False for tool in discovered.tools)


def test_discovered_schemas_match_normative_bounds() -> None:
    server = create_server(RecordingClient())
    properties = _properties(server)

    assert properties["cmc_crypto_map"]["listing_status"]["items"]["enum"] == [
        "active",
        "inactive",
        "untracked",
    ]
    assert properties["cmc_crypto_map"]["listing_status"]["default"] == ["active"]
    assert properties["cmc_crypto_map"]["symbols"]["minItems"] == 1
    assert properties["cmc_crypto_map"]["symbols"]["maxItems"] == 100
    assert properties["cmc_crypto_map"]["symbols"]["uniqueItems"] is True

    for name in ("cmc_crypto_info", "cmc_quotes_latest"):
        for selector in ("ids", "slugs", "symbols"):
            assert properties[name][selector]["minItems"] == 1
            assert properties[name][selector]["maxItems"] == 100
            assert properties[name][selector]["uniqueItems"] is True
    assert properties["cmc_quotes_latest"]["convert"]["maxItems"] == 3
    assert properties["cmc_quotes_latest"]["convert"]["default"] == ["USD"]
    assert properties["cmc_listings_latest"]["limit"]["maximum"] == 250
    assert properties["cmc_fear_greed_historical"]["limit"]["maximum"] == 500
    for name in ("cmc_cmc100_historical", "cmc_cmc20_historical"):
        assert properties[name]["count"]["maximum"] == 10
        assert properties[name]["interval"]["enum"] == ["5m", "15m", "daily"]
        assert properties[name]["time_start"]["minLength"] == 1
        assert properties[name]["time_end"]["minLength"] == 1


@pytest.mark.asyncio
async def test_every_tool_calls_its_single_allowlisted_route_and_preserves_envelope() -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        for name in EXPECTED_NAMES:
            result = await client.call_tool(name, CALL_ARGS[name])
            assert not result.is_error
            assert result.structured_content["status"]["error_code"] == 0
    assert [route for route, _ in recording.calls] == [ROUTES[name] for name in EXPECTED_NAMES]


@pytest.mark.asyncio
async def test_unknown_arguments_and_cross_field_errors_are_rejected_before_upstream() -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        unknown = await client.call_tool("cmc_global_metrics_latest", {"unexpected": True})
        selectors = await client.call_tool("cmc_crypto_info", {"ids": [1], "symbols": ["BTC"]})
        invalid_time = await client.call_tool(
            "cmc_cmc100_historical", {"time_start": "2025-01-02", "time_end": "2025-01-01"}
        )
    assert unknown.is_error
    assert selectors.is_error
    assert invalid_time.is_error
    assert recording.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("cmc_quotes_latest", {"ids": [1], "convert": ["USD,EUR,GBP,JPY"]}),
        ("cmc_crypto_map", {"symbols": ["BTC,BTC"]}),
        ("cmc_crypto_info", {"symbols": ["BTC ETH"]}),
        ("cmc_quotes_latest", {"symbols": ["X" * 65]}),
    ],
)
async def test_list_items_cannot_smuggle_separators_past_bounds(
    tool: str, arguments: dict[str, Any]
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert recording.calls == []


@pytest.mark.asyncio
async def test_server_identity_and_combined_selector_error_text() -> None:
    from importlib.metadata import version

    async with Client(create_server(RecordingClient())) as client:
        assert client.server_info.name == "coinmarketcap-keyless-mcp"
        assert client.server_info.version == version("coinmarketcap-keyless-mcp")
        result = await client.call_tool("cmc_crypto_map", {"symbols": ["BTC"], "start": 2})
    assert result.is_error
    assert result.content[0].text == (
        "Error executing tool cmc_crypto_map: INVALID_ARGUMENT: symbols cannot be combined "
        "with explicit listing_status, start, limit, or sort"
    )


INVALID_ARGUMENT_CASES = [
    (
        "cmc_crypto_map",
        {"listing_status": ["active", "active"]},
        "listing_status must not contain duplicate values",
    ),
    ("cmc_crypto_map", {"symbols": ["BTC", "BTC"]}, "symbols must not contain duplicate values"),
    ("cmc_crypto_info", {}, "exactly one of ids, slugs, or symbols must be supplied"),
    (
        "cmc_crypto_info",
        {"ids": [1], "slugs": ["bitcoin"]},
        "exactly one of ids, slugs, or symbols must be supplied",
    ),
    ("cmc_quotes_latest", {}, "exactly one of ids, slugs, or symbols must be supplied"),
    ("cmc_quotes_latest", {"ids": [1, 1]}, "ids must not contain duplicate values"),
    ("cmc_quotes_latest", {"slugs": ["a", "a"]}, "slugs must not contain duplicate values"),
    (
        "cmc_quotes_latest",
        {"ids": [1], "convert": ["USD", "USD"]},
        "convert must not contain duplicate values",
    ),
    (
        "cmc_listings_latest",
        {"convert": ["USD", "USD"]},
        "convert must not contain duplicate values",
    ),
    (
        "cmc_global_metrics_latest",
        {"convert": ["USD", "USD"]},
        "convert must not contain duplicate values",
    ),
    (
        "cmc_cmc100_historical",
        {"time_start": "not-a-time"},
        "time_start must be a Unix timestamp or ISO-8601 timestamp",
    ),
    (
        "cmc_cmc20_historical",
        {"time_start": "2024-02-01T00:00:00Z", "time_end": "2024-01-01T00:00:00Z"},
        "time_start must be less than or equal to time_end",
    ),
    (
        "cmc_crypto_map",
        {"symbols": ["BTC"], "limit": 5},
        "symbols cannot be combined with explicit listing_status, start, limit, or sort",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments", "message"), INVALID_ARGUMENT_CASES)
async def test_cross_field_validation_surfaces_invalid_argument_with_message(
    tool: str, arguments: dict[str, Any], message: str
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert result.content[0].text == f"Error executing tool {tool}: INVALID_ARGUMENT: {message}"
    assert recording.calls == []  # Rejected locally, before any upstream request.


# --- v1.1 E1-R additions (verification/v1.1-e1r-contract-review.md) -------------------

E1R_NAMES = [
    "cmc_simple_price",
    "cmc_crypto_categories",
    "cmc_crypto_category",
    "cmc_price_conversion",
    "cmc_exchange_map",
]
_TOKEN = {"maxLength": 64, "minLength": 1, "pattern": "^[^,\\s]+$", "type": "string"}
_CONVERT = {
    "default": ["USD"],
    "items": _TOKEN,
    "maxItems": 3,
    "minItems": 1,
    "title": "Convert",
    "type": "array",
    "uniqueItems": True,
}
_START = {"default": 1, "minimum": 1, "title": "Start", "type": "integer"}


def _limit(maximum: int) -> dict[str, Any]:
    return {"default": 100, "maximum": maximum, "minimum": 1, "title": "Limit", "type": "integer"}


def _optional(schema: dict[str, Any], title: str) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}], "default": None, "title": title}


def _selector(title: str, items: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": items,
        "maxItems": 100,
        "minItems": 1,
        "title": title,
        "type": "array",
        "uniqueItems": True,
    }


E1R_SCHEMAS = {
    "cmc_simple_price": {
        "additionalProperties": False,
        "properties": {
            "ids": _selector("Ids", {"minimum": 1, "type": "integer"}),
            "slugs": _selector("Slugs", {"pattern": "^[0-9a-z-]+$", "type": "string"}),
            "symbols": _selector("Symbols", _TOKEN),
            "convert": _CONVERT,
        },
        "title": "cmc_simple_priceArguments",
        "type": "object",
    },
    "cmc_crypto_categories": {
        "additionalProperties": False,
        "properties": {"start": _START, "limit": _limit(100)},
        "title": "cmc_crypto_categoriesArguments",
        "type": "object",
    },
    "cmc_crypto_category": {
        "additionalProperties": False,
        "properties": {
            "id": {
                "maxLength": 64,
                "minLength": 1,
                "pattern": "^[A-Za-z0-9]+$",
                "title": "Id",
                "type": "string",
            },
            "start": _START,
            "limit": _limit(100),
            "convert": _CONVERT,
        },
        "required": ["id"],
        "title": "cmc_crypto_categoryArguments",
        "type": "object",
    },
    "cmc_price_conversion": {
        "additionalProperties": False,
        "properties": {
            "amount": {
                "maximum": 1000000000000.0,
                "minimum": 1e-08,
                "title": "Amount",
                "type": "number",
            },
            "id": _optional({"minimum": 1, "type": "integer"}, "Id"),
            "symbol": _optional(_TOKEN, "Symbol"),
            "convert": _optional(_TOKEN, "Convert"),
            "convert_id": _optional({"minimum": 1, "type": "integer"}, "Convert Id"),
        },
        "required": ["amount"],
        "title": "cmc_price_conversionArguments",
        "type": "object",
    },
    "cmc_exchange_map": {
        "additionalProperties": False,
        "properties": {
            "listing_status": {
                "default": ["active"],
                "items": {"enum": ["active", "inactive", "untracked"], "type": "string"},
                "minItems": 1,
                "title": "Listing Status",
                "type": "array",
                "uniqueItems": True,
            },
            "start": _START,
            "limit": _limit(500),
            "sort": {
                "default": "id",
                "enum": ["id", "volume_24h"],
                "title": "Sort",
                "type": "string",
            },
        },
        "title": "cmc_exchange_mapArguments",
        "type": "object",
    },
}


@pytest.mark.asyncio
async def test_e1r_discovered_schemas_are_exact_strict_snapshots() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert list(tools)[13:18] == E1R_NAMES
    for name in E1R_NAMES:
        assert tools[name].input_schema == E1R_SCHEMAS[name]


E1R_QUERIES = [
    ("cmc_simple_price", {"ids": [1, 1027]}, {"id": "1,1027", "convert": "USD"}),
    (
        "cmc_simple_price",
        {"slugs": ["bitcoin"], "convert": ["USD", "EUR"]},
        {"slug": "bitcoin", "convert": "USD,EUR"},
    ),
    ("cmc_simple_price", {"symbols": ["BTC", "eth"]}, {"symbol": "BTC,eth", "convert": "USD"}),
    ("cmc_crypto_categories", {}, {"start": 1, "limit": 100}),
    ("cmc_crypto_categories", {"start": 3, "limit": 1}, {"start": 3, "limit": 1}),
    (
        "cmc_crypto_category",
        {"id": "605e2ce9d41eae1066535f7c"},
        {"id": "605e2ce9d41eae1066535f7c", "start": 1, "limit": 100, "convert": "USD"},
    ),
    (
        "cmc_crypto_category",
        {"id": "A" * 64, "start": 2, "limit": 50, "convert": ["EUR", "BTC"]},
        {"id": "A" * 64, "start": 2, "limit": 50, "convert": "EUR,BTC"},
    ),
    ("cmc_price_conversion", {"amount": 1, "id": 1}, {"amount": "1", "id": 1, "convert": "USD"}),
    (
        "cmc_price_conversion",
        {"amount": 2.5, "symbol": "BTC", "convert": "EUR"},
        {"amount": "2.5", "symbol": "BTC", "convert": "EUR"},
    ),
    (
        "cmc_price_conversion",
        {"amount": 1e-8, "id": 1, "convert_id": 2781},
        {"amount": "0.00000001", "id": 1, "convert_id": 2781},
    ),
    (
        "cmc_price_conversion",
        {"amount": 1e12, "symbol": "ETH"},
        {"amount": "1000000000000", "symbol": "ETH", "convert": "USD"},
    ),
    (
        "cmc_exchange_map",
        {},
        {"listing_status": "active", "start": 1, "limit": 100, "sort": "id"},
    ),
    (
        "cmc_exchange_map",
        {
            "listing_status": ["inactive", "untracked"],
            "start": 5,
            "limit": 500,
            "sort": "volume_24h",
        },
        {"listing_status": "inactive,untracked", "start": 5, "limit": 500, "sort": "volume_24h"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments", "query"), E1R_QUERIES)
async def test_e1r_exact_query_serialization_and_omitted_provider_keys(
    tool: str, arguments: dict[str, Any], query: dict[str, Any]
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error
    assert recording.calls == [(ROUTES[tool], query)]


E1R_INVALID = [
    # S1: exactly one selector; omitted provider parameters are unknown arguments.
    ("cmc_simple_price", {}),
    ("cmc_simple_price", {"ids": [1], "symbols": ["BTC"]}),
    ("cmc_simple_price", {"ids": [1], "slugs": ["bitcoin"], "symbols": ["BTC"]}),
    ("cmc_simple_price", {"ids": []}),
    ("cmc_simple_price", {"ids": [1, 1]}),
    ("cmc_simple_price", {"symbols": ["BTC,ETH"]}),
    ("cmc_simple_price", {"ids": [1], "convert": ["USD", "USD"]}),
    ("cmc_simple_price", {"ids": [1], "convert": ["USD", "EUR", "GBP", "JPY"]}),
    ("cmc_simple_price", {"ids": [1], "convert_id": "2781"}),
    ("cmc_simple_price", {"ids": [1], "skip_invalid": True}),
    ("cmc_simple_price", {"ids": [1], "precision": 2}),
    # S2
    ("cmc_crypto_categories", {"start": 0}),
    ("cmc_crypto_categories", {"start": True}),
    ("cmc_crypto_categories", {"limit": 0}),
    ("cmc_crypto_categories", {"limit": 101}),
    ("cmc_crypto_categories", {"limit": False}),
    ("cmc_crypto_categories", {"limit": "5"}),
    ("cmc_crypto_categories", {"id": "605e"}),
    ("cmc_crypto_categories", {"symbol": "BTC"}),
    # S3
    ("cmc_crypto_category", {}),
    ("cmc_crypto_category", {"id": ""}),
    ("cmc_crypto_category", {"id": "A" * 65}),
    ("cmc_crypto_category", {"id": "605e-2ce9"}),
    ("cmc_crypto_category", {"id": "605e 2ce9"}),
    ("cmc_crypto_category", {"id": "605e,2ce9"}),
    ("cmc_crypto_category", {"id": "605e&limit=5"}),
    ("cmc_crypto_category", {"id": "605e\n"}),
    ("cmc_crypto_category", {"id": 605}),
    ("cmc_crypto_category", {"id": "605e", "start": True}),
    ("cmc_crypto_category", {"id": "605e", "limit": 101}),
    ("cmc_crypto_category", {"id": "605e", "convert": ["USD", "USD"]}),
    ("cmc_crypto_category", {"id": "605e", "convert_id": 2781}),
    # S4: amount
    ("cmc_price_conversion", {"id": 1}),
    ("cmc_price_conversion", {"amount": True, "id": 1}),
    ("cmc_price_conversion", {"amount": "1", "id": 1}),
    ("cmc_price_conversion", {"amount": 0, "id": 1}),
    ("cmc_price_conversion", {"amount": 9e-9, "id": 1}),
    ("cmc_price_conversion", {"amount": 1e12 + 1, "id": 1}),
    ("cmc_price_conversion", {"amount": -1, "id": 1}),
    # S4: source and target
    ("cmc_price_conversion", {"amount": 1}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "symbol": "BTC"}),
    ("cmc_price_conversion", {"amount": 1, "id": 0}),
    ("cmc_price_conversion", {"amount": 1, "id": True}),
    ("cmc_price_conversion", {"amount": 1, "symbol": "BTC,ETH"}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "convert": "USD", "convert_id": 2781}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "convert": "USD,EUR"}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "convert": ["USD"]}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "convert": "US D"}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "convert_id": True}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "convert_id": "2781"}),
    ("cmc_price_conversion", {"amount": 1, "id": 1, "time": "2024-01-01"}),
    # S5
    ("cmc_exchange_map", {"listing_status": []}),
    ("cmc_exchange_map", {"listing_status": ["active", "active"]}),
    ("cmc_exchange_map", {"listing_status": ["delisted"]}),
    ("cmc_exchange_map", {"start": 0}),
    ("cmc_exchange_map", {"start": True}),
    ("cmc_exchange_map", {"limit": 501}),
    ("cmc_exchange_map", {"sort": "volume"}),
    ("cmc_exchange_map", {"sort": "cmc_rank"}),
    ("cmc_exchange_map", {"slug": "binance"}),
    ("cmc_exchange_map", {"aux": "status"}),
    ("cmc_exchange_map", {"crypto_id": 1}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments"), E1R_INVALID)
async def test_e1r_invalid_arguments_are_rejected_before_any_transport_call(
    tool: str, arguments: dict[str, Any]
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert recording.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("cmc_simple_price", {}, "exactly one of ids, slugs, or symbols must be supplied"),
        ("cmc_price_conversion", {"amount": 1}, "exactly one of id or symbol must be supplied"),
        (
            "cmc_price_conversion",
            {"amount": 1, "id": 1, "symbol": "BTC"},
            "exactly one of id or symbol must be supplied",
        ),
        (
            "cmc_price_conversion",
            {"amount": 1, "id": 1, "convert": "USD", "convert_id": 2781},
            "at most one of convert or convert_id may be supplied",
        ),
        (
            "cmc_exchange_map",
            {"listing_status": ["active", "active"]},
            "listing_status must not contain duplicate values",
        ),
        (
            "cmc_crypto_category",
            {"id": "605e", "convert": ["USD", "USD"]},
            "convert must not contain duplicate values",
        ),
    ],
)
async def test_e1r_cross_field_errors_are_invalid_argument_with_message(
    tool: str, arguments: dict[str, Any], message: str
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert result.content[0].text == f"Error executing tool {tool}: INVALID_ARGUMENT: {message}"
    assert recording.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
async def test_price_conversion_rejects_non_finite_amounts_before_transport(amount: float) -> None:
    recording = RecordingClient()
    server = create_server(recording)
    with pytest.raises(ToolError, match="Input should be a finite number"):
        await server.call_tool("cmc_price_conversion", {"amount": amount, "id": 1})
    assert recording.calls == []


@pytest.mark.asyncio
async def test_price_conversion_usd_default_is_handler_only_and_preserves_case() -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        await client.call_tool("cmc_price_conversion", {"amount": 3, "symbol": "eth"})
        await client.call_tool("cmc_price_conversion", {"amount": 3, "id": 1, "convert": "eur"})
    assert tools["cmc_price_conversion"].input_schema["properties"]["convert"]["default"] is None
    assert recording.calls == [
        (ROUTES["cmc_price_conversion"], {"amount": "3", "symbol": "eth", "convert": "USD"}),
        (ROUTES["cmc_price_conversion"], {"amount": "3", "id": 1, "convert": "eur"}),
    ]


# --- E1-R finding L1: the shared Ids type rejects booleans at runtime -----------------

_SKIP_INVALID = {"default": False, "title": "Skip Invalid", "type": "boolean"}
# Frozen v1 discoverable schemas, pinned as published before the L1 correction.
FROZEN_IDS_SCHEMAS = {
    "cmc_crypto_info": {
        "additionalProperties": False,
        "properties": {
            "ids": _selector("Ids", {"minimum": 1, "type": "integer"}),
            "slugs": _selector("Slugs", {"pattern": "^[0-9a-z-]+$", "type": "string"}),
            "symbols": _selector("Symbols", _TOKEN),
            "skip_invalid": _SKIP_INVALID,
        },
        "title": "cmc_crypto_infoArguments",
        "type": "object",
    },
    "cmc_quotes_latest": {
        "additionalProperties": False,
        "properties": {
            "ids": _selector("Ids", {"minimum": 1, "type": "integer"}),
            "slugs": _selector("Slugs", {"pattern": "^[0-9a-z-]+$", "type": "string"}),
            "symbols": _selector("Symbols", _TOKEN),
            "convert": _CONVERT,
            "skip_invalid": _SKIP_INVALID,
        },
        "title": "cmc_quotes_latestArguments",
        "type": "object",
    },
}
IDS_TOOLS = ["cmc_crypto_info", "cmc_quotes_latest", "cmc_simple_price"]


@pytest.mark.asyncio
async def test_ids_schemas_are_unchanged_by_strict_runtime_validation() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    for name, schema in FROZEN_IDS_SCHEMAS.items():
        assert tools[name].input_schema == schema
    assert tools["cmc_simple_price"].input_schema == E1R_SCHEMAS["cmc_simple_price"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", IDS_TOOLS)
@pytest.mark.parametrize("ids", [[True], [False], [1, True], [False, 2], ["1"], [1.0]])
async def test_ids_reject_booleans_and_non_integers_before_any_transport_call(
    tool: str, ids: list[Any]
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, {"ids": ids})
    assert result.is_error
    assert "INVALID_ARGUMENT" not in result.content[0].text  # schema-level rejection
    assert recording.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", IDS_TOOLS)
async def test_ids_accept_ordinary_positive_integers(tool: str) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, {"ids": [1, 1027]})
    assert not result.is_error
    assert [(route, params["id"]) for route, params in recording.calls] == [
        (ROUTES[tool], "1,1027")
    ]


# --- v1.1 E2-A DEX identity foundation (verification/v1.1-e2a-contract-review.md) ------

E2A_NAMES = ["cmc_dex_platform_list", "cmc_dex_token_price"]
_PLATFORM_EDGE = r"[^\s\x00-\x1f\x7f-\x9f&=?#]"
_PLATFORM_CHAR = r"[^\x00-\x1f\x7f-\x9f&=?#]"
E2A_SCHEMAS = {
    "cmc_dex_platform_list": {
        "additionalProperties": False,
        "properties": {},
        "title": "cmc_dex_platform_listArguments",
        "type": "object",
    },
    "cmc_dex_token_price": {
        "additionalProperties": False,
        "properties": {
            "platform": {
                "maxLength": 64,
                "minLength": 1,
                "pattern": f"^{_PLATFORM_EDGE}(?:{_PLATFORM_CHAR}*{_PLATFORM_EDGE})?$",
                "title": "Platform",
                "type": "string",
            },
            "address": {
                "maxLength": 128,
                "minLength": 1,
                "pattern": "^[A-Za-z0-9_.:-]{1,128}$",
                "title": "Address",
                "type": "string",
            },
        },
        "required": ["platform", "address"],
        "title": "cmc_dex_token_priceArguments",
        "type": "object",
    },
}


@pytest.mark.asyncio
async def test_e2a_discovered_schemas_are_exact_and_earlier_tools_unchanged() -> None:
    async with Client(create_server(RecordingClient())) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert len(tools) == 22
    assert list(tools)[18:20] == E2A_NAMES
    for name in E2A_NAMES:
        assert tools[name].input_schema == E2A_SCHEMAS[name]
    for name in E1R_NAMES:
        assert tools[name].input_schema == E1R_SCHEMAS[name]
    for name, schema in FROZEN_IDS_SCHEMAS.items():
        assert tools[name].input_schema == schema


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "query"),
    [
        (
            {"platform": "Ethereum", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
            {"platform": "Ethereum", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
        ),
        (  # case preserved exactly, never normalized
            {"platform": "eThErEuM", "address": "0xa0B86991C6218B36"},
            {"platform": "eThErEuM", "address": "0xa0B86991C6218B36"},
        ),
        (  # inner spaces, punctuation and non-ASCII names; non-EVM address forms
            {"platform": "BNB Smart Chain (BEP20)", "address": "So1111111111111111111"},
            {"platform": "BNB Smart Chain (BEP20)", "address": "So1111111111111111111"},
        ),
        (
            {"platform": "B² Network", "address": "EQ:abc_d.e-f"},
            {"platform": "B² Network", "address": "EQ:abc_d.e-f"},
        ),
        (
            {"platform": "x" * 64, "address": "a" * 128},
            {"platform": "x" * 64, "address": "a" * 128},
        ),
        ({"platform": "1", "address": "a"}, {"platform": "1", "address": "a"}),
    ],
)
async def test_dex_token_price_serializes_exactly_platform_and_address(
    arguments: dict[str, Any], query: dict[str, Any]
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool("cmc_dex_token_price", arguments)
    assert not result.is_error
    assert recording.calls == [(ROUTES["cmc_dex_token_price"], query)]
    assert list(recording.calls[0][1]) == ["platform", "address"]


@pytest.mark.asyncio
async def test_dex_platform_list_sends_no_query() -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool("cmc_dex_platform_list", {})
    assert not result.is_error
    assert recording.calls == [(ROUTES["cmc_dex_platform_list"], None)]


E2A_INVALID = [
    ("cmc_dex_platform_list", {"platform": "Ethereum"}),
    ("cmc_dex_platform_list", {"start": 1}),
    ("cmc_dex_token_price", {}),
    ("cmc_dex_token_price", {"platform": "Ethereum"}),
    ("cmc_dex_token_price", {"address": "0xA0b8"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8", "network": "x"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8", "convert": "USD"}),
    # platform: length, whitespace, control characters, query delimiters, type
    ("cmc_dex_token_price", {"platform": "", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "x" * 65, "address": "a"}),
    ("cmc_dex_token_price", {"platform": " Ethereum", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Ethereum ", "address": "a"}),
    ("cmc_dex_token_price", {"platform": " ", "address": "a"}),
    ("cmc_dex_token_price", {"platform": " Ethereum", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Ethereum\n", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Eth\tereum", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Eth\x00ereum", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Eth\x7fereum", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Eth\x85ereum", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Ethereum&address=0xdead", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Ethereum=1", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Ethereum?x", "address": "a"}),
    ("cmc_dex_token_price", {"platform": "Ethereum#x", "address": "a"}),
    ("cmc_dex_token_price", {"platform": 1, "address": "a"}),
    ("cmc_dex_token_price", {"platform": ["Ethereum"], "address": "a"}),
    # address: length, pattern, whitespace, delimiters, path characters, type
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": ""}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "a" * 129}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": " 0xA0b8"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8\n"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8&platform=x"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8/../x"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8?x"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8%26x"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": "0xA0b8,0xC0de"}),
    ("cmc_dex_token_price", {"platform": "Ethereum", "address": 1}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments"), E2A_INVALID)
async def test_e2a_invalid_arguments_are_rejected_before_any_transport_call(
    tool: str, arguments: dict[str, Any]
) -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert recording.calls == []

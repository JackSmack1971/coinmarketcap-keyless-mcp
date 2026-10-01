from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

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
}


def _properties(server) -> dict[str, dict[str, Any]]:
    return {
        tool.name: tool.parameters["properties"] for tool in server._tool_manager._tools.values()
    }


@pytest.mark.asyncio
async def test_in_process_discovery_exposes_exact_13_tools() -> None:
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

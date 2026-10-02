from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

import coinmarketcap_keyless_mcp.server as server_module
from coinmarketcap_keyless_mcp.contracts import ROUTES, TOOL_CONTRACTS
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
from coinmarketcap_keyless_mcp.server import create_server

NAMES = [contract.name for contract in TOOL_CONTRACTS]
NESTED_ENVELOPE = {
    "status": {"error_code": 0, "notice": None, "meta": {"request_id": "fixture"}},
    "data": {"rows": [{"price": 123.45, "percent_change": -7.25, "nested": {"x": [1, 2]}}]},
}


class RecordingClient:
    def __init__(
        self, result: dict[str, Any] | None = None, error: CmcClientError | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.result = result or NESTED_ENVELOPE
        self.error = error

    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((route, params))
        if self.error:
            raise self.error
        return self.result


def schema(server, name: str) -> dict[str, Any]:
    return server._tool_manager._tools[name].parameters["properties"]


@pytest.mark.asyncio
async def test_server_factory_uses_default_client_when_none_is_injected(monkeypatch) -> None:
    recording = RecordingClient()
    monkeypatch.setattr(server_module, "KeylessHttpClient", lambda: recording)
    async with Client(create_server()) as client:
        result = await client.call_tool("cmc_fear_greed_latest", {})
    assert not result.is_error
    assert recording.calls == [(ROUTES["cmc_fear_greed_latest"], None)]


@pytest.mark.asyncio
async def test_discovered_surface_and_schema_are_exactly_bounded() -> None:
    server = create_server(RecordingClient())
    async with Client(server) as client:
        tools = await client.list_tools()
    assert [tool.name for tool in tools.tools] == NAMES
    assert len(NAMES) == 24
    assert all(
        set(tool.input_schema["properties"]) == set(schema(server, tool.name))
        for tool in tools.tools
    )
    assert all(tool.input_schema.get("additionalProperties") is False for tool in tools.tools)
    assert schema(server, "cmc_listings_latest")["sort"]["enum"] == [
        "market_cap",
        "market_cap_strict",
        "name",
        "symbol",
        "date_added",
        "price",
        "circulating_supply",
        "total_supply",
        "max_supply",
        "num_market_pairs",
        "market_cap_by_total_supply_strict",
        "volume_24h",
        "volume_7d",
        "volume_30d",
        "percent_change_1h",
        "percent_change_24h",
        "percent_change_7d",
    ]
    assert set(schema(server, "cmc_altcoin_season_historical")["timeframe"]["enum"]) == {
        "7d",
        "30d",
        "90d",
    }
    for name in (
        "cmc_fear_greed_latest",
        "cmc_altcoin_season_latest",
        "cmc_cmc100_latest",
        "cmc_cmc20_latest",
    ):
        assert schema(server, name) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["listing_status", "start", "limit", "sort"])
async def test_crypto_map_rejects_explicit_default_with_symbols(field: str) -> None:
    recording = RecordingClient()
    args = {
        "symbols": ["BTC"],
        field: {"listing_status": ["active"], "start": 1, "limit": 100, "sort": "id"}[field],
    }
    async with Client(create_server(recording)) as client:
        result = await client.call_tool("cmc_crypto_map", args)
    assert result.is_error
    assert recording.calls == []


@pytest.mark.asyncio
async def test_selectors_are_exactly_one_and_collection_rules_are_runtime_enforced() -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        results = []
        for args in (
            {},
            {"ids": [1]},
            {"slugs": ["bitcoin"]},
            {"symbols": ["BTC"]},
            {"ids": [1], "symbols": ["BTC"]},
            {"ids": [1], "slugs": ["bitcoin"], "symbols": ["BTC"]},
            {"ids": [1, 1]},
            {"ids": [0]},
            {"slugs": ["Bitcoin"]},
            {"ids": []},
        ):
            results.append(await client.call_tool("cmc_crypto_info", args))
        duplicate_convert = await client.call_tool(
            "cmc_quotes_latest", {"ids": [1], "convert": ["USD", "USD"]}
        )
    assert [result.is_error for result in results] == [
        True,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
    ]
    assert duplicate_convert.is_error
    assert len(recording.calls) == 3
    assert recording.calls == [
        (ROUTES["cmc_crypto_info"], {"id": "1", "skip_invalid": False}),
        (ROUTES["cmc_crypto_info"], {"slug": "bitcoin", "skip_invalid": False}),
        (ROUTES["cmc_crypto_info"], {"symbol": "BTC", "skip_invalid": False}),
    ]


@pytest.mark.asyncio
async def test_serialization_output_and_historical_validation() -> None:
    recording = RecordingClient()
    async with Client(create_server(recording)) as client:
        await client.call_tool("cmc_crypto_info", {"ids": [1, 2], "skip_invalid": True})
        await client.call_tool("cmc_quotes_latest", {"symbols": ["BTC"], "convert": ["USD", "EUR"]})
        await client.call_tool(
            "cmc_listings_latest", {"start": 2, "limit": 3, "convert": ["USD"], "sort_dir": "asc"}
        )
        await client.call_tool(
            "cmc_cmc100_historical",
            {"time_start": "2025-01-01", "time_end": "2025-01-01T05:00:00-05:00"},
        )
        equal_bounds = await client.call_tool(
            "cmc_cmc20_historical",
            {"time_start": "2025-01-01T00:00:00Z", "time_end": "2024-12-31T19:00:00-05:00"},
        )
        invalid = await client.call_tool("cmc_cmc20_historical", {"time_start": "not-a-time"})
        reversed_bounds = await client.call_tool(
            "cmc_cmc20_historical", {"time_start": "2", "time_end": "1"}
        )
    assert not equal_bounds.is_error
    assert invalid.is_error and reversed_bounds.is_error
    assert recording.calls == [
        (ROUTES["cmc_crypto_info"], {"id": "1,2", "skip_invalid": True}),
        (
            ROUTES["cmc_quotes_latest"],
            {"symbol": "BTC", "convert": "USD,EUR", "skip_invalid": False},
        ),
        (
            ROUTES["cmc_listings_latest"],
            {"start": 2, "limit": 3, "convert": "USD", "sort": "market_cap", "sort_dir": "asc"},
        ),
        (
            ROUTES["cmc_cmc100_historical"],
            {
                "count": 5,
                "interval": "daily",
                "time_start": "2025-01-01",
                "time_end": "2025-01-01T05:00:00-05:00",
            },
        ),
        (
            ROUTES["cmc_cmc20_historical"],
            {
                "count": 5,
                "interval": "daily",
                "time_start": "2025-01-01T00:00:00Z",
                "time_end": "2024-12-31T19:00:00-05:00",
            },
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", list(ErrorCode))
async def test_client_errors_are_mcp_failures_with_stable_classification(code: ErrorCode) -> None:
    recording = RecordingClient(error=CmcClientError(code, "fixture failure"))
    async with Client(create_server(recording)) as client:
        result = await client.call_tool("cmc_fear_greed_latest", {})
    assert result.is_error
    assert code.value in result.content[0].text
    assert result.structured_content is None

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

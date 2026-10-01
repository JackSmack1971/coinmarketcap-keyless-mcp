import ast
import importlib
from dataclasses import fields
from pathlib import Path

import coinmarketcap_keyless_mcp as package
from coinmarketcap_keyless_mcp import BASE_URL, ROUTES, TOOL_CONTRACTS
from coinmarketcap_keyless_mcp import contracts


EXPECTED_ROUTES = {
    "cmc_crypto_map": "/v1/cryptocurrency/map",
    "cmc_crypto_info": "/v2/cryptocurrency/info",
    "cmc_quotes_latest": "/v3/cryptocurrency/quotes/latest",
    "cmc_listings_latest": "/v3/cryptocurrency/listings/latest",
    "cmc_global_metrics_latest": "/v1/global-metrics/quotes/latest",
    "cmc_fear_greed_latest": "/v3/fear-and-greed/latest",
    "cmc_fear_greed_historical": "/v3/fear-and-greed/historical",
    "cmc_altcoin_season_latest": "/v1/altcoin-season-index/latest",
    "cmc_altcoin_season_historical": "/v1/altcoin-season-index/historical",
    "cmc_cmc100_latest": "/v3/index/cmc100-latest",
    "cmc_cmc100_historical": "/v3/index/cmc100-historical",
    "cmc_cmc20_latest": "/v3/index/cmc20-latest",
    "cmc_cmc20_historical": "/v3/index/cmc20-historical",
}

EXPECTED_DESCRIPTIONS = {
    "cmc_crypto_map": "Resolve CoinMarketCap cryptocurrency IDs and canonical identifiers. Prefer this tool before symbol-based research when an asset's CMC ID is not already known.",
    "cmc_crypto_info": "Get CoinMarketCap metadata for known cryptocurrencies. Numeric CMC IDs are preferred because symbols are not globally unique.",
    "cmc_quotes_latest": "Get the latest CoinMarketCap market quotes for a known set of cryptocurrencies. Prefer CMC IDs over symbols when identity ambiguity matters.",
    "cmc_listings_latest": "Get a ranked, paginated list of active cryptocurrencies with current market data. Use this tool for market breadth/ranking; use cmc_quotes_latest for a known small asset set.",
    "cmc_global_metrics_latest": "Get CoinMarketCap's latest aggregate crypto-market metrics, including market capitalization, volume, and dominance measures.",
    "cmc_fear_greed_latest": "Get the latest CoinMarketCap Crypto Fear and Greed Index value and classification.",
    "cmc_fear_greed_historical": "Get historical CoinMarketCap Crypto Fear and Greed values, paginated from the provider's daily series.",
    "cmc_altcoin_season_latest": "Get the latest CoinMarketCap Altcoin Season Index snapshot.",
    "cmc_altcoin_season_historical": "Get CoinMarketCap Altcoin Season Index history for one provider-supported timeframe.",
    "cmc_cmc100_latest": "Get the latest CoinMarketCap 100 Index value, constituents, and constituent weights.",
    "cmc_cmc100_historical": "Get historical CoinMarketCap 100 Index values at a provider-supported interval.",
    "cmc_cmc20_latest": "Get the latest CoinMarketCap 20 Index value, constituents, and constituent weights.",
    "cmc_cmc20_historical": "Get historical CoinMarketCap 20 Index values at a provider-supported interval.",
}


def test_package_imports_successfully() -> None:
    assert importlib.import_module("coinmarketcap_keyless_mcp")


def test_phase_zero_locks_exact_route_surface() -> None:
    assert BASE_URL == "https://pro-api.coinmarketcap.com/public-api"
    assert dict(ROUTES) == EXPECTED_ROUTES
    assert {contract.name for contract in TOOL_CONTRACTS} == set(EXPECTED_ROUTES)
    assert len(TOOL_CONTRACTS) == 13
    assert all(contract.method == "GET" for contract in TOOL_CONTRACTS)
    assert all("/dex/" not in route.lower() for route in ROUTES.values())


def test_contracts_are_one_to_one_and_described() -> None:
    assert len({contract.name for contract in TOOL_CONTRACTS}) == 13
    assert len(set(ROUTES.values())) == 13
    assert {contract.name: contract.description for contract in TOOL_CONTRACTS} == EXPECTED_DESCRIPTIONS


def test_public_contract_has_no_auth_or_generic_proxy_surface() -> None:
    assert set(package.__all__) == {"BASE_URL", "ROUTES", "TOOL_CONTRACTS"}
    assert {field.name for field in fields(contracts.ToolContract)} == {
        "name",
        "description",
        "route",
        "method",
    }
    assert not any(
        forbidden in name.lower()
        for name in package.__all__
        for forbidden in ("api_key", "auth", "bearer", "credential", "header", "proxy", "query")
    )


def test_phase_zero_contract_module_remains_data_only() -> None:
    tree = ast.parse(Path(contracts.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported_modules <= {"dataclasses", "types", "typing"}

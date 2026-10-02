import ast
import importlib
from dataclasses import fields
from pathlib import Path

import coinmarketcap_keyless_mcp as package
from coinmarketcap_keyless_mcp import BASE_URL, ROUTES, TOOL_CONTRACTS, contracts

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


# v1.1 E1-R additions (verification/v1.1-e1r-contract-review.md), pinned separately so
# the frozen v1 maps above stay byte-for-byte unchanged.
E1R_ROUTES = {
    "cmc_simple_price": "/v2/simple/price",
    "cmc_crypto_categories": "/v1/cryptocurrency/categories",
    "cmc_crypto_category": "/v1/cryptocurrency/category",
    "cmc_price_conversion": "/v2/tools/price-conversion",
    "cmc_exchange_map": "/v1/exchange/map",
}

E1R_DESCRIPTIONS = {
    "cmc_simple_price": "Get the latest simple CoinMarketCap price for a known set of cryptocurrencies, selected by exactly one of ids, slugs, or symbols. Prefer CMC IDs over symbols when identity ambiguity matters.",
    "cmc_crypto_categories": "Get a paginated list of CoinMarketCap cryptocurrency categories with their category IDs. Use cmc_crypto_category to fetch one category's coins.",
    "cmc_crypto_category": "Get one CoinMarketCap cryptocurrency category and a paginated page of its coins with market quotes. Obtain category IDs from cmc_crypto_categories.",
    "cmc_price_conversion": "Convert an amount of one source cryptocurrency, identified by exactly one of id or symbol, into exactly one target currency, identified by exactly one of convert or convert_id (USD if neither is given).",
    "cmc_exchange_map": "Resolve CoinMarketCap exchange IDs and slugs, paginated and filterable by listing status.",
}


# v1.1 E2-A additions (verification/v1.1-e2a-contract-review.md), pinned separately.
E2A_ROUTES = {
    "cmc_dex_platform_list": "/v1/dex/platform/list",
    "cmc_dex_token_price": "/v1/dex/token/price",
}

E2A_DESCRIPTIONS = {
    "cmc_dex_platform_list": "Get the list of blockchain platforms supported by CoinMarketCap DEX data; use it to discover platform names accepted by DEX tools.",
    "cmc_dex_token_price": "Get current CoinMarketCap DEX price data for one token identified by platform name and token contract address; use platform-list to discover platform names.",
}

# v1.1 E2-B addition (verification/v1.1-e2b-contract-review.md), pinned separately.
E2B_ROUTES = {"cmc_dex_token": "/v1/dex/token"}

E2B_DESCRIPTIONS = {
    "cmc_dex_token": "Get CoinMarketCap DEX token detail (metadata, market, liquidity and pool fields) for one token identified by platform name and token contract address; use platform-list to discover platform names.",
}

# v1.1 E2-C addition (verification/v1.1-e2c-contract-review.md), pinned separately.
E2C_ROUTES = {"cmc_dex_platform_detail": "/v1/dex/platform/detail"}

E2C_DESCRIPTIONS = {
    "cmc_dex_platform_detail": "Get CoinMarketCap DEX detail for one blockchain platform identified by platform name; use platform-list to discover platform names.",
}

# v1.1 E2-D addition (verification/v1.1-e2d-contract-review.md), pinned separately.
E2D_ROUTES = {"cmc_dex_holders_count": "/v1/dex/holders/count"}

E2D_DESCRIPTIONS = {
    "cmc_dex_holders_count": "Get the CoinMarketCap DEX holder count for one token identified by platform name and token contract address; use platform-list to discover platform names.",
}

# v1.1 E2-E addition (verification/v1.1-e2e-contract-review.md), pinned separately.
E2E_ROUTES = {"cmc_dex_security_detail": "/v1/dex/security/detail"}

E2E_DESCRIPTIONS = {
    "cmc_dex_security_detail": "Get CoinMarketCap DEX token security audit records for one token identified by platform name and token contract address; returns provider and third-party vendor data as-is, not a safety guarantee; use platform-list to discover platform names.",
}

# Deferred (D5) and excluded (D15, D17) DEX candidates from V1_1_CAPABILITY_INVENTORY.md.
ABSENT_DEX = {
    "cmc_dex_token_liquidity": "/v1/dex/token-liquidity/query",
    "cmc_dex_holders_list": "/v1/dex/holders/list",
    "cmc_dex_holders_detail": "/v1/dex/holders/detail",
}

# Approved at E0 but not authorized by any accepted slice contract yet.
UNAUTHORIZED_DEX = {
    "cmc_dex_spot_pairs_latest": "/v4/dex/spot-pairs/latest",
    "cmc_dex_pair_quotes_latest": "/v4/dex/pairs/quotes/latest",
    "cmc_dex_token_pools": "/v1/dex/token/pools",
    "cmc_dex_search": "/v1/dex/search",
    "cmc_dex_transactions": "/v1/dex/tokens/transactions",
    "cmc_dex_liquidity_change_list": "/v1/dex/liquidity-change/list",
    "cmc_dex_kline_candles": "/v1/k-line/candles",
    "cmc_dex_kline_points": "/v1/k-line/points",
}


def test_package_imports_successfully() -> None:
    assert importlib.import_module("coinmarketcap_keyless_mcp")


def test_phase_zero_locks_exact_route_surface() -> None:
    assert BASE_URL == "https://pro-api.coinmarketcap.com/public-api"
    assert dict(ROUTES) == {
        **EXPECTED_ROUTES,
        **E1R_ROUTES,
        **E2A_ROUTES,
        **E2B_ROUTES,
        **E2C_ROUTES,
        **E2D_ROUTES,
        **E2E_ROUTES,
    }
    assert {contract.name for contract in TOOL_CONTRACTS} == (
        set(EXPECTED_ROUTES)
        | set(E1R_ROUTES)
        | set(E2A_ROUTES)
        | set(E2B_ROUTES)
        | set(E2C_ROUTES)
        | set(E2D_ROUTES)
        | set(E2E_ROUTES)
    )
    assert len(TOOL_CONTRACTS) == 24
    assert all(contract.method == "GET" for contract in TOOL_CONTRACTS)
    # Exactly the E2-A, E2-B, E2-C, E2-D and E2-E DEX routes; no other DEX surface.
    assert {name: route for name, route in ROUTES.items() if "/dex/" in route.lower()} == {
        **E2A_ROUTES,
        **E2B_ROUTES,
        **E2C_ROUTES,
        **E2D_ROUTES,
        **E2E_ROUTES,
    }
    # D16 is the only holder route: holder list/detail, trend-list and tag-count stay absent.
    assert [route for route in ROUTES.values() if "/holders" in route.lower()] == [
        "/v1/dex/holders/count"
    ]


def test_deferred_and_excluded_dex_candidates_are_absent() -> None:
    assert not set(ABSENT_DEX) & set(ROUTES)
    assert not set(ABSENT_DEX.values()) & set(ROUTES.values())


def test_dex_routes_without_an_accepted_slice_contract_are_absent() -> None:
    assert not set(UNAUTHORIZED_DEX) & set(ROUTES)
    assert not set(UNAUTHORIZED_DEX.values()) & set(ROUTES.values())
    assert not any("k-line" in route for route in ROUTES.values())


def test_contracts_are_one_to_one_and_described() -> None:
    assert len({contract.name for contract in TOOL_CONTRACTS}) == 24
    assert len(set(ROUTES.values())) == 24
    assert {contract.name: contract.description for contract in TOOL_CONTRACTS} == {
        **EXPECTED_DESCRIPTIONS,
        **E1R_DESCRIPTIONS,
        **E2A_DESCRIPTIONS,
        **E2B_DESCRIPTIONS,
        **E2C_DESCRIPTIONS,
        **E2D_DESCRIPTIONS,
        **E2E_DESCRIPTIONS,
    }


def test_frozen_v1_contracts_are_unchanged_and_first() -> None:
    frozen = TOOL_CONTRACTS[:13]
    assert [contract.name for contract in frozen] == list(EXPECTED_ROUTES)
    assert {contract.name: contract.route for contract in frozen} == EXPECTED_ROUTES
    assert {contract.name: contract.description for contract in frozen} == EXPECTED_DESCRIPTIONS
    assert [contract.name for contract in TOOL_CONTRACTS[13:18]] == list(E1R_ROUTES)
    assert {contract.name: contract.route for contract in TOOL_CONTRACTS[13:18]} == E1R_ROUTES
    assert {
        contract.name: contract.description for contract in TOOL_CONTRACTS[13:18]
    } == E1R_DESCRIPTIONS
    assert [contract.name for contract in TOOL_CONTRACTS[18:20]] == list(E2A_ROUTES)
    assert {contract.name: contract.route for contract in TOOL_CONTRACTS[18:20]} == E2A_ROUTES
    assert {
        contract.name: contract.description for contract in TOOL_CONTRACTS[18:20]
    } == E2A_DESCRIPTIONS
    assert {contract.name: contract.route for contract in TOOL_CONTRACTS[20:21]} == E2B_ROUTES
    assert {
        contract.name: contract.description for contract in TOOL_CONTRACTS[20:21]
    } == E2B_DESCRIPTIONS
    assert {contract.name: contract.route for contract in TOOL_CONTRACTS[21:22]} == E2C_ROUTES
    assert {
        contract.name: contract.description for contract in TOOL_CONTRACTS[21:22]
    } == E2C_DESCRIPTIONS
    assert {contract.name: contract.route for contract in TOOL_CONTRACTS[22:23]} == E2D_ROUTES
    assert {
        contract.name: contract.description for contract in TOOL_CONTRACTS[22:23]
    } == E2D_DESCRIPTIONS
    assert [contract.name for contract in TOOL_CONTRACTS[23:]] == list(E2E_ROUTES)


def test_e1r_price_conversion_description_names_exactly_one_target() -> None:
    assert "exactly one target currency" in E1R_DESCRIPTIONS["cmc_price_conversion"]


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

"""The deliberately narrow Phase 0 public route and tool contract.

This module contains data only. It does not construct URLs from caller input,
perform network requests, or expose a generic route proxy.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

BASE_URL: Final = "https://pro-api.coinmarketcap.com/public-api"


@dataclass(frozen=True, slots=True)
class ToolContract:
    """One MCP tool's stable name, description, and one fixed GET route."""

    name: str
    description: str
    route: str
    method: str = "GET"


_CONTRACTS = (
    ToolContract(
        "cmc_crypto_map",
        "Resolve CoinMarketCap cryptocurrency IDs and canonical identifiers. Prefer this tool before symbol-based research when an asset's CMC ID is not already known.",
        "/v1/cryptocurrency/map",
    ),
    ToolContract(
        "cmc_crypto_info",
        "Get CoinMarketCap metadata for known cryptocurrencies. Numeric CMC IDs are preferred because symbols are not globally unique.",
        "/v2/cryptocurrency/info",
    ),
    ToolContract(
        "cmc_quotes_latest",
        "Get the latest CoinMarketCap market quotes for a known set of cryptocurrencies. Prefer CMC IDs over symbols when identity ambiguity matters.",
        "/v3/cryptocurrency/quotes/latest",
    ),
    ToolContract(
        "cmc_listings_latest",
        "Get a ranked, paginated list of active cryptocurrencies with current market data. Use this tool for market breadth/ranking; use cmc_quotes_latest for a known small asset set.",
        "/v3/cryptocurrency/listings/latest",
    ),
    ToolContract(
        "cmc_global_metrics_latest",
        "Get CoinMarketCap's latest aggregate crypto-market metrics, including market capitalization, volume, and dominance measures.",
        "/v1/global-metrics/quotes/latest",
    ),
    ToolContract(
        "cmc_fear_greed_latest",
        "Get the latest CoinMarketCap Crypto Fear and Greed Index value and classification.",
        "/v3/fear-and-greed/latest",
    ),
    ToolContract(
        "cmc_fear_greed_historical",
        "Get historical CoinMarketCap Crypto Fear and Greed values, paginated from the provider's daily series.",
        "/v3/fear-and-greed/historical",
    ),
    ToolContract(
        "cmc_altcoin_season_latest",
        "Get the latest CoinMarketCap Altcoin Season Index snapshot.",
        "/v1/altcoin-season-index/latest",
    ),
    ToolContract(
        "cmc_altcoin_season_historical",
        "Get CoinMarketCap Altcoin Season Index history for one provider-supported timeframe.",
        "/v1/altcoin-season-index/historical",
    ),
    ToolContract(
        "cmc_cmc100_latest",
        "Get the latest CoinMarketCap 100 Index value, constituents, and constituent weights.",
        "/v3/index/cmc100-latest",
    ),
    ToolContract(
        "cmc_cmc100_historical",
        "Get historical CoinMarketCap 100 Index values at a provider-supported interval.",
        "/v3/index/cmc100-historical",
    ),
    ToolContract(
        "cmc_cmc20_latest",
        "Get the latest CoinMarketCap 20 Index value, constituents, and constituent weights.",
        "/v3/index/cmc20-latest",
    ),
    ToolContract(
        "cmc_cmc20_historical",
        "Get historical CoinMarketCap 20 Index values at a provider-supported interval.",
        "/v3/index/cmc20-historical",
    ),
    # v1.1 E1-R Standard additions (verification/v1.1-e1r-contract-review.md).
    ToolContract(
        "cmc_simple_price",
        "Get the latest simple CoinMarketCap price for a known set of cryptocurrencies, selected by exactly one of ids, slugs, or symbols. Prefer CMC IDs over symbols when identity ambiguity matters.",
        "/v2/simple/price",
    ),
    ToolContract(
        "cmc_crypto_categories",
        "Get a paginated list of CoinMarketCap cryptocurrency categories with their category IDs. Use cmc_crypto_category to fetch one category's coins.",
        "/v1/cryptocurrency/categories",
    ),
    ToolContract(
        "cmc_crypto_category",
        "Get one CoinMarketCap cryptocurrency category and a paginated page of its coins with market quotes. Obtain category IDs from cmc_crypto_categories.",
        "/v1/cryptocurrency/category",
    ),
    ToolContract(
        "cmc_price_conversion",
        "Convert an amount of one source cryptocurrency, identified by exactly one of id or symbol, into exactly one target currency, identified by exactly one of convert or convert_id (USD if neither is given).",
        "/v2/tools/price-conversion",
    ),
    ToolContract(
        "cmc_exchange_map",
        "Resolve CoinMarketCap exchange IDs and slugs, paginated and filterable by listing status.",
        "/v1/exchange/map",
    ),
    # v1.1 E2-A DEX identity foundation (verification/v1.1-e2a-contract-review.md).
    ToolContract(
        "cmc_dex_platform_list",
        "Get the list of blockchain platforms supported by CoinMarketCap DEX data; use it to discover platform names accepted by DEX tools.",
        "/v1/dex/platform/list",
    ),
    ToolContract(
        "cmc_dex_token_price",
        "Get current CoinMarketCap DEX price data for one token identified by platform name and token contract address; use platform-list to discover platform names.",
        "/v1/dex/token/price",
    ),
    # v1.1 E2-B DEX token detail (verification/v1.1-e2b-contract-review.md).
    ToolContract(
        "cmc_dex_token",
        "Get CoinMarketCap DEX token detail (metadata, market, liquidity and pool fields) for one token identified by platform name and token contract address; use platform-list to discover platform names.",
        "/v1/dex/token",
    ),
    # v1.1 E2-C DEX platform detail (verification/v1.1-e2c-contract-review.md).
    ToolContract(
        "cmc_dex_platform_detail",
        "Get CoinMarketCap DEX detail for one blockchain platform identified by platform name; use platform-list to discover platform names.",
        "/v1/dex/platform/detail",
    ),
)

TOOL_CONTRACTS: Final[tuple[ToolContract, ...]] = _CONTRACTS
ROUTES: Final[Mapping[str, str]] = MappingProxyType(
    {contract.name: contract.route for contract in _CONTRACTS}
)

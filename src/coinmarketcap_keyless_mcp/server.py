"""The Phase 2 MCP tool surface, with one explicit route per tool."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .client import KeylessHttpClient
from .contracts import ROUTES, TOOL_CONTRACTS
from .errors import CmcClientError, ErrorCode
from .models import (
    CategoryId,
    ConversionAmount,
    DexAddress,
    DexPlatform,
    ExchangeSort,
    Ids,
    IndexInterval,
    ListingSort,
    ListingStatus,
    ListToken,
    MapSort,
    ProviderEnvelope,
    Slugs,
    SortDirection,
    StrictPositiveInt,
    Symbols,
    Timeframe,
    UniqueConversions,
    UniqueSymbols,
    dex_platform_detail_params,
    dex_token_params,
    dex_token_price_params,
    price_conversion_params,
    require_exactly_one_selector,
    require_unique,
    validate_time_bounds,
)


def _description(name: str) -> str:
    return next(contract.description for contract in TOOL_CONTRACTS if contract.name == name)


@contextmanager
def _invalid_argument() -> Iterator[None]:
    """Report a cross-field validation failure as INVALID_ARGUMENT with its message.

    MCP SDK 2.2 hides the text of any non-ToolError exception raised inside a tool,
    so local validation must surface as a ToolError to stay classifiable.
    """

    try:
        yield
    except ValueError as exc:
        raise ToolError(f"{ErrorCode.INVALID_ARGUMENT}: {exc}") from exc


def _query_selector(name: str, values: list[Any]) -> tuple[str, str]:
    return {"ids": "id", "slugs": "slug", "symbols": "symbol"}[name], ",".join(
        str(value) for value in values
    )


def _index_history_params(
    time_start: str, time_end: str, count: int, interval: IndexInterval
) -> dict[str, Any]:
    """Shared validation and query for the CMC100/CMC20 history tools.

    An omitted bound arrives as "" (the schema forbids an explicit empty string),
    which keeps the published schema a plain string as PLAN.md specifies.
    """

    start, end = time_start or None, time_end or None
    with _invalid_argument():
        validate_time_bounds(start, end)
    params: dict[str, Any] = {"count": count, "interval": interval}
    if start is not None:
        params["time_start"] = start
    if end is not None:
        params["time_end"] = end
    return params


def create_server(client: KeylessHttpClient | None = None) -> MCPServer:
    """Create the high-level MCP server with the exact 20-tool contract."""

    upstream = client if client is not None else KeylessHttpClient()
    server = MCPServer("coinmarketcap-keyless-mcp", version=version("coinmarketcap-keyless-mcp"))

    async def get(route: str, params: dict[str, Any] | None = None) -> ProviderEnvelope:
        """Call the injected Phase 1 boundary without hiding its stable error code."""

        try:
            return await upstream.get(route, params)
        except CmcClientError as exc:
            raise ToolError(f"{exc.code}: {exc.message}") from exc

    @server.tool(name="cmc_crypto_map", description=_description("cmc_crypto_map"))
    async def cmc_crypto_map(
        listing_status: list[ListingStatus] = Field(
            default=["active"], min_length=1, json_schema_extra={"uniqueItems": True}
        ),
        start: int = Field(default=1, ge=1),
        limit: int = Field(default=100, ge=1, le=500),
        sort: MapSort = "id",
        symbols: UniqueSymbols = Field(default_factory=list),
    ) -> ProviderEnvelope:
        with _invalid_argument():
            if symbols:
                require_unique(symbols, "symbols")
                if listing_status != ["active"] or start != 1 or limit != 100 or sort != "id":
                    raise ValueError(
                        "symbols cannot be combined with explicit listing_status, start, limit, "
                        "or sort"
                    )
            else:
                require_unique(listing_status, "listing_status")
                if any(
                    value not in {"active", "inactive", "untracked"} for value in listing_status
                ):
                    raise ValueError("listing_status contains an unsupported value")
        if symbols:
            return await get(ROUTES["cmc_crypto_map"], {"symbol": ",".join(symbols)})
        return await get(
            ROUTES["cmc_crypto_map"],
            {
                "listing_status": ",".join(listing_status),
                "start": start,
                "limit": limit,
                "sort": sort,
            },
        )

    @server.tool(name="cmc_crypto_info", description=_description("cmc_crypto_info"))
    async def cmc_crypto_info(
        ids: Ids = Field(default_factory=list),
        slugs: Slugs = Field(default_factory=list),
        symbols: Symbols = Field(default_factory=list),
        skip_invalid: bool = False,
    ) -> ProviderEnvelope:
        with _invalid_argument():
            name, values = require_exactly_one_selector(ids=ids, slugs=slugs, symbols=symbols)
        key, value = _query_selector(name, values)
        return await get(ROUTES["cmc_crypto_info"], {key: value, "skip_invalid": skip_invalid})

    @server.tool(name="cmc_quotes_latest", description=_description("cmc_quotes_latest"))
    async def cmc_quotes_latest(
        ids: Ids = Field(default_factory=list),
        slugs: Slugs = Field(default_factory=list),
        symbols: Symbols = Field(default_factory=list),
        convert: UniqueConversions = Field(default=["USD"]),
        skip_invalid: bool = False,
    ) -> ProviderEnvelope:
        with _invalid_argument():
            name, values = require_exactly_one_selector(ids=ids, slugs=slugs, symbols=symbols)
            require_unique(convert, "convert")
        key, value = _query_selector(name, values)
        return await get(
            ROUTES["cmc_quotes_latest"],
            {key: value, "convert": ",".join(convert), "skip_invalid": skip_invalid},
        )

    @server.tool(name="cmc_listings_latest", description=_description("cmc_listings_latest"))
    async def cmc_listings_latest(
        start: int = Field(default=1, ge=1),
        limit: int = Field(default=100, ge=1, le=250),
        convert: UniqueConversions = Field(default=["USD"]),
        sort: ListingSort = "market_cap",
        sort_dir: SortDirection = "desc",
    ) -> ProviderEnvelope:
        with _invalid_argument():
            require_unique(convert, "convert")
        return await get(
            ROUTES["cmc_listings_latest"],
            {
                "start": start,
                "limit": limit,
                "convert": ",".join(convert),
                "sort": sort,
                "sort_dir": sort_dir,
            },
        )

    @server.tool(
        name="cmc_global_metrics_latest", description=_description("cmc_global_metrics_latest")
    )
    async def cmc_global_metrics_latest(
        convert: UniqueConversions = Field(default=["USD"]),
    ) -> ProviderEnvelope:
        with _invalid_argument():
            require_unique(convert, "convert")
        return await get(ROUTES["cmc_global_metrics_latest"], {"convert": ",".join(convert)})

    @server.tool(name="cmc_fear_greed_latest", description=_description("cmc_fear_greed_latest"))
    async def cmc_fear_greed_latest() -> ProviderEnvelope:
        return await get(ROUTES["cmc_fear_greed_latest"])

    @server.tool(
        name="cmc_fear_greed_historical", description=_description("cmc_fear_greed_historical")
    )
    async def cmc_fear_greed_historical(
        start: int = Field(default=1, ge=1), limit: int = Field(default=50, ge=1, le=500)
    ) -> ProviderEnvelope:
        return await get(ROUTES["cmc_fear_greed_historical"], {"start": start, "limit": limit})

    @server.tool(
        name="cmc_altcoin_season_latest", description=_description("cmc_altcoin_season_latest")
    )
    async def cmc_altcoin_season_latest() -> ProviderEnvelope:
        return await get(ROUTES["cmc_altcoin_season_latest"])

    @server.tool(
        name="cmc_altcoin_season_historical",
        description=_description("cmc_altcoin_season_historical"),
    )
    async def cmc_altcoin_season_historical(timeframe: Timeframe = "7d") -> ProviderEnvelope:
        return await get(ROUTES["cmc_altcoin_season_historical"], {"timeframe": timeframe})

    @server.tool(name="cmc_cmc100_latest", description=_description("cmc_cmc100_latest"))
    async def cmc_cmc100_latest() -> ProviderEnvelope:
        return await get(ROUTES["cmc_cmc100_latest"])

    @server.tool(name="cmc_cmc100_historical", description=_description("cmc_cmc100_historical"))
    async def cmc_cmc100_historical(
        time_start: str = Field(default_factory=str, min_length=1),
        time_end: str = Field(default_factory=str, min_length=1),
        count: int = Field(default=5, ge=1, le=10),
        interval: IndexInterval = "daily",
    ) -> ProviderEnvelope:
        return await get(
            ROUTES["cmc_cmc100_historical"],
            _index_history_params(time_start, time_end, count, interval),
        )

    @server.tool(name="cmc_cmc20_latest", description=_description("cmc_cmc20_latest"))
    async def cmc_cmc20_latest() -> ProviderEnvelope:
        return await get(ROUTES["cmc_cmc20_latest"])

    @server.tool(name="cmc_cmc20_historical", description=_description("cmc_cmc20_historical"))
    async def cmc_cmc20_historical(
        time_start: str = Field(default_factory=str, min_length=1),
        time_end: str = Field(default_factory=str, min_length=1),
        count: int = Field(default=5, ge=1, le=10),
        interval: IndexInterval = "daily",
    ) -> ProviderEnvelope:
        return await get(
            ROUTES["cmc_cmc20_historical"],
            _index_history_params(time_start, time_end, count, interval),
        )

    @server.tool(name="cmc_simple_price", description=_description("cmc_simple_price"))
    async def cmc_simple_price(
        ids: Ids = Field(default_factory=list),
        slugs: Slugs = Field(default_factory=list),
        symbols: Symbols = Field(default_factory=list),
        convert: UniqueConversions = Field(default=["USD"]),
    ) -> ProviderEnvelope:
        with _invalid_argument():
            name, values = require_exactly_one_selector(ids=ids, slugs=slugs, symbols=symbols)
            require_unique(convert, "convert")
        key, value = _query_selector(name, values)
        return await get(ROUTES["cmc_simple_price"], {key: value, "convert": ",".join(convert)})

    @server.tool(name="cmc_crypto_categories", description=_description("cmc_crypto_categories"))
    async def cmc_crypto_categories(
        start: StrictPositiveInt = 1,
        limit: StrictPositiveInt = Field(default=100, le=100),
    ) -> ProviderEnvelope:
        return await get(ROUTES["cmc_crypto_categories"], {"start": start, "limit": limit})

    @server.tool(name="cmc_crypto_category", description=_description("cmc_crypto_category"))
    async def cmc_crypto_category(
        id: CategoryId,
        start: StrictPositiveInt = 1,
        limit: StrictPositiveInt = Field(default=100, le=100),
        convert: UniqueConversions = Field(default=["USD"]),
    ) -> ProviderEnvelope:
        with _invalid_argument():
            require_unique(convert, "convert")
        return await get(
            ROUTES["cmc_crypto_category"],
            {"id": id, "start": start, "limit": limit, "convert": ",".join(convert)},
        )

    @server.tool(name="cmc_price_conversion", description=_description("cmc_price_conversion"))
    async def cmc_price_conversion(
        amount: ConversionAmount,
        id: StrictPositiveInt | None = None,
        symbol: ListToken | None = None,
        convert: ListToken | None = None,
        convert_id: StrictPositiveInt | None = None,
    ) -> ProviderEnvelope:
        with _invalid_argument():
            params = price_conversion_params(amount, id, symbol, convert, convert_id)
        return await get(ROUTES["cmc_price_conversion"], params)

    @server.tool(name="cmc_exchange_map", description=_description("cmc_exchange_map"))
    async def cmc_exchange_map(
        listing_status: list[ListingStatus] = Field(
            default=["active"], min_length=1, json_schema_extra={"uniqueItems": True}
        ),
        start: StrictPositiveInt = 1,
        limit: StrictPositiveInt = Field(default=100, le=500),
        sort: ExchangeSort = "id",
    ) -> ProviderEnvelope:
        with _invalid_argument():
            require_unique(listing_status, "listing_status")
        return await get(
            ROUTES["cmc_exchange_map"],
            {
                "listing_status": ",".join(listing_status),
                "start": start,
                "limit": limit,
                "sort": sort,
            },
        )

    @server.tool(name="cmc_dex_platform_list", description=_description("cmc_dex_platform_list"))
    async def cmc_dex_platform_list() -> ProviderEnvelope:
        return await get(ROUTES["cmc_dex_platform_list"])

    @server.tool(name="cmc_dex_token_price", description=_description("cmc_dex_token_price"))
    async def cmc_dex_token_price(platform: DexPlatform, address: DexAddress) -> ProviderEnvelope:
        return await get(ROUTES["cmc_dex_token_price"], dex_token_price_params(platform, address))

    @server.tool(name="cmc_dex_token", description=_description("cmc_dex_token"))
    async def cmc_dex_token(platform: DexPlatform, address: DexAddress) -> ProviderEnvelope:
        return await get(ROUTES["cmc_dex_token"], dex_token_params(platform, address))

    @server.tool(
        name="cmc_dex_platform_detail", description=_description("cmc_dex_platform_detail")
    )
    async def cmc_dex_platform_detail(platform: DexPlatform) -> ProviderEnvelope:
        return await get(ROUTES["cmc_dex_platform_detail"], dex_platform_detail_params(platform))

    # MCP v2's high-level argument base defaults to ignoring extra fields. The
    # Phase 2 contract requires strict rejection, so tighten each registered
    # generated model before the server is exposed to a client.
    for tool in server._tool_manager._tools.values():  # noqa: SLF001
        argument_model = tool.fn_metadata.arg_model  # noqa: SLF001
        argument_model.model_config["extra"] = "forbid"
        argument_model.model_rebuild(force=True)
        tool.parameters = argument_model.model_json_schema(by_alias=True)  # noqa: SLF001

    # The SDK materializes defaults before calling a tool, but the map contract
    # distinguishes omitted fields from explicitly supplied defaults. Preserve
    # that presence information through the SDK's validated-arguments boundary
    # for this one cross-field rule without exposing another public argument.
    map_tool = server._tool_manager._tools["cmc_crypto_map"]  # noqa: SLF001
    map_model = map_tool.fn_metadata.arg_model
    original_dump = map_model.model_dump_one_level

    def dump_with_presence(model: Any) -> dict[str, Any]:
        values = original_dump(model)
        values["_provided_fields"] = frozenset(model.model_fields_set)
        return values

    map_model.model_dump_one_level = dump_with_presence
    original_map_fn = map_tool.fn

    async def map_with_presence(
        *, _provided_fields: frozenset[str] = frozenset(), **kwargs: Any
    ) -> Any:
        symbols = kwargs.get("symbols")
        if symbols and any(
            field in _provided_fields for field in ("listing_status", "start", "limit", "sort")
        ):
            raise ToolError(
                f"{ErrorCode.INVALID_ARGUMENT}: symbols cannot be combined with explicit listing_status, start, limit, or sort"
            )
        return await original_map_fn(**kwargs)

    map_tool.fn = map_with_presence

    return server

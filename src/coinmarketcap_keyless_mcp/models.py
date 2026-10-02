"""Typed Phase 2 tool parameter building blocks and local validation helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Annotated, Any, Literal, TypedDict, TypeVar

from pydantic import Field, StringConstraints

T = TypeVar("T")


class ProviderEnvelope(TypedDict):
    status: dict[str, Any]
    data: Any


# Provider list parameters are comma-joined, so items must not contain separators.
ListToken = Annotated[str, StringConstraints(pattern=r"^[^,\s]+$", min_length=1, max_length=64)]

# Strict items: the published schema is "type": "integer", which JSON booleans are not.
Ids = Annotated[
    list[Annotated[int, Field(strict=True, ge=1)]],
    Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
]
Slugs = Annotated[
    list[Annotated[str, StringConstraints(pattern=r"^[0-9a-z-]+$")]],
    Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
]
Symbols = Annotated[
    list[ListToken],
    Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
]
UniqueConversions = Annotated[
    list[ListToken],
    Field(min_length=1, max_length=3, json_schema_extra={"uniqueItems": True}),
]
UniqueIds = Annotated[
    list[Annotated[int, Field(ge=1)]],
    Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
]
UniqueSlugs = Annotated[
    list[Annotated[str, StringConstraints(pattern=r"^[0-9a-z-]+$")]],
    Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
]
UniqueSymbols = Annotated[
    list[ListToken],
    Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
]

ListingStatus = Literal["active", "inactive", "untracked"]
MapSort = Literal["id", "cmc_rank"]
ListingSort = Literal[
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
SortDirection = Literal["asc", "desc"]
Timeframe = Literal["7d", "30d", "90d"]
IndexInterval = Literal["5m", "15m", "daily"]

# v1.1 E1-R building blocks. Strict integers reject booleans and numeric strings.
StrictPositiveInt = Annotated[int, Field(strict=True, ge=1)]
CategoryId = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9]+$", min_length=1, max_length=64)
]
ConversionAmount = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=1e-8, le=1e12)]
ExchangeSort = Literal["id", "volume_24h"]

# v1.1 E2-A. Platform names keep their provider case and may contain inner spaces,
# punctuation or non-ASCII letters, but never control characters, query delimiters
# or leading/trailing whitespace. No local platform enum is frozen.
_PLATFORM_CHAR = r"[^\x00-\x1f\x7f-\x9f&=?#]"
_PLATFORM_EDGE = r"[^\s\x00-\x1f\x7f-\x9f&=?#]"
DexPlatform = Annotated[
    str,
    StringConstraints(
        pattern=rf"^{_PLATFORM_EDGE}(?:{_PLATFORM_CHAR}*{_PLATFORM_EDGE})?$",
        min_length=1,
        max_length=64,
    ),
]
DexAddress = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,128}$", min_length=1, max_length=128)
]


def require_exactly_one_selector(**selectors: list[T] | None) -> tuple[str, list[T]]:
    present = [(name, values) for name, values in selectors.items() if values]
    if len(present) != 1:
        raise ValueError("exactly one of ids, slugs, or symbols must be supplied")
    name, values = present[0]
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicate values")
    return name, values


def require_unique(values: Iterable[T], name: str) -> None:
    values = list(values)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicate values")


def validate_time(value: str | None, name: str) -> float | None:
    if value is None:
        return None
    if not value:
        raise ValueError(f"{name} must not be empty")
    try:
        timestamp = float(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be a Unix timestamp or ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        timestamp = parsed.timestamp()
    if not isfinite(timestamp):
        raise ValueError(f"{name} must be finite")
    return timestamp


def validate_time_bounds(time_start: str | None, time_end: str | None) -> None:
    start = validate_time(time_start, "time_start")
    end = validate_time(time_end, "time_end")
    if start is not None and end is not None and start > end:
        raise ValueError("time_start must be less than or equal to time_end")


def plain_decimal(amount: float) -> str:
    """Render a finite amount as a plain decimal string, never in exponent notation."""

    text = format(Decimal(repr(float(amount))), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def price_conversion_params(
    amount: float,
    id: int | None,
    symbol: str | None,
    convert: str | None,
    convert_id: int | None,
) -> dict[str, str | int]:
    """Validate the price-conversion source/target rules and build its exact query.

    USD is the handler default only when neither target is supplied; it is not a
    schema default.
    """

    if (id is None) == (symbol is None):
        raise ValueError("exactly one of id or symbol must be supplied")
    if convert is not None and convert_id is not None:
        raise ValueError("at most one of convert or convert_id may be supplied")
    params: dict[str, str | int] = {"amount": plain_decimal(amount)}
    if id is not None:
        params["id"] = id
    else:
        params["symbol"] = symbol  # type: ignore[assignment]
    if convert_id is not None:
        params["convert_id"] = convert_id
    else:
        params["convert"] = convert if convert is not None else "USD"
    return params


def dex_token_price_params(platform: str, address: str) -> dict[str, str]:
    """Build the exact DEX token-price query: provider keys platform then address.

    Values are passed through unchanged; case is never normalized.
    """

    return {"platform": platform, "address": address}


def dex_token_params(platform: str, address: str) -> dict[str, str]:
    """Build the exact DEX token-detail query: provider keys platform then address.

    Values are passed through unchanged; case is never normalized.
    """

    return {"platform": platform, "address": address}


def dex_platform_detail_params(platform: str) -> dict[str, str]:
    """Build the exact DEX platform-detail query: the single provider key platformName.

    The public argument is ``platform``; the value is passed through unchanged.
    """

    return {"platformName": platform}


def dex_holders_count_params(platform: str, address: str) -> dict[str, str]:
    """Build the exact DEX holder-count query: provider keys platform then tokenAddress.

    The public argument ``address`` is sent as ``tokenAddress``; values pass through unchanged.
    """

    return {"platform": platform, "tokenAddress": address}


def dex_security_detail_params(platform: str, address: str) -> dict[str, str]:
    """Build the exact DEX security-detail query: provider keys platformName then address.

    The public argument ``platform`` is sent as ``platformName``; values pass through unchanged.
    """

    return {"platformName": platform, "address": address}

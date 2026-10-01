"""Typed Phase 2 tool parameter building blocks and local validation helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from math import isfinite
from typing import Annotated, Any, Literal, TypedDict, TypeVar

from pydantic import Field, StringConstraints

T = TypeVar("T")


class ProviderEnvelope(TypedDict):
    status: dict[str, Any]
    data: Any

# Provider list parameters are comma-joined, so items must not contain separators.
ListToken = Annotated[str, StringConstraints(pattern=r"^[^,\s]+$", min_length=1, max_length=64)]

Ids = Annotated[
    list[Annotated[int, Field(ge=1)]],
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


def require_exactly_one_selector(**selectors: list[T] | None) -> tuple[str, list[T]]:
    present = [(name, values) for name, values in selectors.items() if values]
    if len(present) != 1:
        raise ValueError("exactly one of ids, slugs, or symbols must be supplied")
    name, values = present[0]
    if not values:
        raise ValueError(f"{name} must not be empty")
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

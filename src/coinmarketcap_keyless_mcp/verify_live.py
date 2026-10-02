"""Opt-in, serial live capability verification for the released v1 routes."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable, Mapping

from .client import KeylessHttpClient
from .contracts import BASE_URL, ROUTES
from .errors import CmcClientError, ErrorCode


class CapabilityClassification(StrEnum):
    SUPPORTED = "SUPPORTED"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class LiveProbe:
    tool: str
    params: Mapping[str, Any]
    shape: str

    @property
    def route(self) -> str:
        return ROUTES[self.tool]


# Keep this tuple as the single operator matrix. Its order is the default run order.
LIVE_MATRIX: tuple[LiveProbe, ...] = (
    LiveProbe("cmc_crypto_map", {"symbol": "BTC"}, "asset_list"),
    LiveProbe("cmc_crypto_info", {"id": 1}, "asset_info_mapping"),
    LiveProbe("cmc_quotes_latest", {"id": "1,1027", "convert": "USD"}, "quoted_asset_list"),
    LiveProbe(
        "cmc_listings_latest",
        {"start": 1, "limit": 2, "convert": "USD"},
        "quoted_asset_list",
    ),
    LiveProbe("cmc_global_metrics_latest", {"convert": "USD"}, "global_metrics"),
    LiveProbe("cmc_fear_greed_latest", {}, "fear_greed_latest"),
    LiveProbe("cmc_fear_greed_historical", {"start": 1, "limit": 2}, "fear_greed_history"),
    LiveProbe("cmc_altcoin_season_latest", {}, "altcoin_season_latest"),
    LiveProbe("cmc_altcoin_season_historical", {"timeframe": "7d"}, "altcoin_season_history"),
    LiveProbe("cmc_cmc100_latest", {}, "index_latest"),
    LiveProbe("cmc_cmc100_historical", {"count": 2, "interval": "daily"}, "index_history"),
    LiveProbe("cmc_cmc20_latest", {}, "index_latest"),
    LiveProbe("cmc_cmc20_historical", {"count": 2, "interval": "daily"}, "index_history"),
    LiveProbe("cmc_simple_price", {"id": "1", "convert": "USD"}, "simple_price_list"),
    LiveProbe("cmc_crypto_categories", {"start": 1, "limit": 1}, "category_list"),
    # The category id is provider-owned, so it is read from the categories route
    # (the preceding probe's result when available) instead of being hard-coded.
    LiveProbe(
        "cmc_crypto_category", {"start": 1, "limit": 1, "convert": "USD"}, "category_results"
    ),
    LiveProbe(
        "cmc_price_conversion", {"amount": "1", "id": 1, "convert": "USD"}, "price_conversion"
    ),
    LiveProbe("cmc_exchange_map", {"start": 1, "limit": 2}, "exchange_list"),
    LiveProbe("cmc_dex_platform_list", {}, "dex_platform_list"),
    # Deterministic fixture from the E2-A contract review: Ethereum USDC.
    LiveProbe(
        "cmc_dex_token_price",
        {"platform": "Ethereum", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
        "dex_token_price",
    ),
    # E2-B contract review: same Ethereum USDC fixture as D4.
    LiveProbe(
        "cmc_dex_token",
        {"platform": "Ethereum", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
        "dex_token",
    ),
    # E2-C contract review: tool argument platform="Ethereum" (observed live in E2-A),
    # sent as the provider query key platformName, as models.dex_platform_detail_params does.
    LiveProbe("cmc_dex_platform_detail", {"platformName": "Ethereum"}, "dex_platform_detail"),
    # E2-D contract review: tool arguments platform/address (the D3/D4 identity), sent as
    # the provider query keys platform and tokenAddress, as models.dex_holders_count_params does.
    LiveProbe(
        "cmc_dex_holders_count",
        {"platform": "Ethereum", "tokenAddress": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
        "dex_holders_count",
    ),
)


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    tool: str
    route: str
    classification: str
    http_status: int | None
    cmc_error_code: int | str | None
    attempts: int
    latency_ms: int
    evidence: str


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_asset(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("id"), int)
        and not isinstance(value.get("id"), bool)
    )


def _nonempty_list_of(value: Any, check: Callable[[Any], bool]) -> bool:
    return isinstance(value, list) and bool(value) and all(check(item) for item in value)


def _is_info_entry(value: Any) -> bool:
    # /v2/cryptocurrency/info keys results by id; symbol lookups map to a list.
    return _is_asset(value) or _nonempty_list_of(value, _is_asset)


def _is_valued_point(value: Any) -> bool:
    """A mapping whose headline "value" is a finite number (fear/greed and index points)."""

    return isinstance(value, Mapping) and _is_number(value.get("value"))


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_priced(value: Any) -> bool:
    return isinstance(value, Mapping) and _is_number(value.get("price"))


def _is_simple_price(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and _is_positive_int(value.get("id"))
        and isinstance(value.get("quotes"), list)
        and any(_is_priced(quote) for quote in value["quotes"])
    )


def _is_category_object(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and _is_nonempty_str(value.get("id"))
        and isinstance(value.get("coins"), list)
    )


def _index_history_points(data: Any) -> Any:
    return data.get("values") if isinstance(data, Mapping) else data


# Minimum endpoint-specific shapes, taken from CoinMarketCap's published response
# schemas. They require the identifying or headline market fields of each route,
# not every documented field, so ordinary provider additions do not fail them.
_SHAPES: dict[str, tuple[Callable[[Any], bool], Callable[[Any], str]]] = {
    "asset_list": (
        lambda data: _nonempty_list_of(data, _is_asset),
        lambda data: "asset list with ids; result count=%d" % len(data),
    ),
    "asset_info_mapping": (
        lambda data: (
            isinstance(data, Mapping)
            and bool(data)
            and all(_is_info_entry(item) for item in data.values())
        ),
        lambda data: "asset metadata keyed by id; result count=%d" % len(data),
    ),
    "quoted_asset_list": (
        lambda data: _nonempty_list_of(
            data,
            lambda item: (
                _is_asset(item)
                and isinstance(item.get("quote"), (list, Mapping))
                and bool(item["quote"])
            ),
        ),
        lambda data: "asset list with ids and quotes; result count=%d" % len(data),
    ),
    "global_metrics": (
        lambda data: (
            isinstance(data, Mapping)
            and isinstance(data.get("quote"), Mapping)
            and bool(data["quote"])
            and all(
                isinstance(quote, Mapping) and _is_number(quote.get("total_market_cap"))
                for quote in data["quote"].values()
            )
        ),
        lambda data: (
            "global metrics with total_market_cap quotes; quote count=%d" % len(data["quote"])
        ),
    ),
    "fear_greed_latest": (
        lambda data: _is_valued_point(data) and isinstance(data.get("value_classification"), str),
        lambda data: "fear and greed value and classification present",
    ),
    "fear_greed_history": (
        lambda data: _nonempty_list_of(data, _is_valued_point),
        lambda data: "fear and greed history with values; result count=%d" % len(data),
    ),
    "altcoin_season_latest": (
        lambda data: isinstance(data, Mapping) and _is_number(data.get("altcoin_index")),
        lambda data: "altcoin season index value present",
    ),
    "altcoin_season_history": (
        lambda data: (
            isinstance(data, Mapping)
            and _nonempty_list_of(
                data.get("points"), lambda item: isinstance(item, Mapping) and bool(item)
            )
        ),
        lambda data: "history mapping with points; result count=%d" % len(data["points"]),
    ),
    "index_latest": (
        lambda data: (
            _is_valued_point(data) and _nonempty_list_of(data.get("constituents"), _is_asset)
        ),
        lambda data: (
            "index value with constituents; constituent count=%d" % len(data["constituents"])
        ),
    ),
    "index_history": (
        lambda data: _nonempty_list_of(_index_history_points(data), _is_valued_point),
        lambda data: (
            "index history with values; result count=%d" % len(_index_history_points(data))
        ),
    ),
    "simple_price_list": (
        lambda data: _nonempty_list_of(data, _is_simple_price),
        lambda data: "simple price list with ids and priced quotes; result count=%d" % len(data),
    ),
    "category_list": (
        lambda data: _nonempty_list_of(
            data,
            lambda item: (
                isinstance(item, Mapping)
                and _is_nonempty_str(item.get("id"))
                and _is_nonempty_str(item.get("name"))
            ),
        ),
        lambda data: "category list with ids and names; result count=%d" % len(data),
    ),
    # data is a provider-owned results map; its keys are not interpreted (C2).
    "category_results": (
        lambda data: (
            isinstance(data, Mapping)
            and bool(data)
            and any(_is_category_object(item) for item in data.values())
        ),
        lambda data: "category results map with id and coins; result count=%d" % len(data),
    ),
    "price_conversion": (
        lambda data: (
            isinstance(data, Mapping)
            and _is_number(data.get("amount"))
            and isinstance(data.get("quote"), Mapping)
            and bool(data["quote"])
            and any(_is_priced(quote) for quote in data["quote"].values())
        ),
        lambda data: "conversion amount with priced quote; quote count=%d" % len(data["quote"]),
    ),
    "exchange_list": (
        lambda data: _nonempty_list_of(
            data,
            lambda item: (
                isinstance(item, Mapping)
                and _is_positive_int(item.get("id"))
                and _is_nonempty_str(item.get("slug"))
            ),
        ),
        lambda data: "exchange list with ids and slugs; result count=%d" % len(data),
    ),
    # pltA is not required: live evidence showed some platform records omit it.
    "dex_platform_list": (
        lambda data: _nonempty_list_of(
            data,
            lambda item: (
                isinstance(item, Mapping)
                and isinstance(item.get("id"), int)
                and not isinstance(item.get("id"), bool)
                and _is_nonempty_str(item.get("n"))
            ),
        ),
        lambda data: "DEX platform list with ids and names; result count=%d" % len(data),
    ),
    "dex_token_price": (
        lambda data: isinstance(data, Mapping) and bool(data) and _is_number(data.get("p")),
        lambda data: "DEX token price with numeric p",
    ),
    # Documentation-derived minimum: addr is not compared with the requested address
    # (case may differ) and n/sym/plt/market fields are not required.
    "dex_token": (
        lambda data: (
            isinstance(data, Mapping) and bool(data) and _is_nonempty_str(data.get("addr"))
        ),
        lambda data: "DEX token detail with addr",
    ),
    # Documentation/D11-derived minimum: n is not compared with the requested name
    # and pltA and other optional PlatformDTO fields are not required.
    "dex_platform_detail": (
        lambda data: (
            isinstance(data, Mapping)
            and _is_positive_int(data.get("id"))
            and _is_nonempty_str(data.get("n"))
        ),
        lambda data: "DEX platform detail with id and name",
    ),
    # Documentation-derived minimum: count is a non-negative int (zero holders is valid);
    # tokenAddress and platformId are not required and not compared with the request.
    "dex_holders_count": (
        lambda data: isinstance(data, Mapping) and _is_nonnegative_int(data.get("count")),
        lambda data: "DEX holder count",
    ),
}


def _first_category_id(data: Any) -> str | None:
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        category_id = data[0].get("id")
        if _is_nonempty_str(category_id):
            return category_id
    return None


class _PrerequisiteFailed(Exception):
    """The category-id lookup failed, so the category route itself was never called.

    Evidence for the category probe must not borrow the lookup route's HTTP status,
    and a lookup failure is never proof of a category-route contract mismatch.
    """

    def __init__(self, classification: CapabilityClassification, detail: str) -> None:
        super().__init__(detail)
        self.classification = classification
        self.detail = detail


_LOOKUP = "category id lookup on " + ROUTES["cmc_crypto_categories"]
_NOT_CALLED = ROUTES["cmc_crypto_category"] + " was not called"


async def _probe_params(
    client: KeylessHttpClient, probe: LiveProbe, category_id: str | None
) -> Mapping[str, Any]:
    if probe.tool != "cmc_crypto_category":
        return probe.params
    if category_id is None:
        try:
            listing = await client.get(ROUTES["cmc_crypto_categories"], {"start": 1, "limit": 1})
        except CmcClientError as exc:
            # Only a 429 carries over; any other lookup outcome (including the
            # lookup route's own contract mismatch) says nothing about S3.
            classification = (
                CapabilityClassification.RATE_LIMITED
                if exc.code is ErrorCode.RATE_LIMITED
                else CapabilityClassification.TRANSIENT_ERROR
            )
            raise _PrerequisiteFailed(
                classification, f"{_LOOKUP} failed ({exc.code.value}); {_NOT_CALLED}"
            ) from exc
        category_id = _first_category_id(listing.get("data"))
    if category_id is None:
        raise _PrerequisiteFailed(
            CapabilityClassification.TRANSIENT_ERROR,
            f"{_LOOKUP} returned no category id; {_NOT_CALLED}",
        )
    return {"id": category_id, **probe.params}


def _shape_check(data: Any, shape: str) -> str:
    accepts, describe = _SHAPES[shape]
    if accepts(data):
        return describe(data)
    raise ValueError("minimum endpoint shape did not pass")


def _positive_unsupported(error: CmcClientError) -> bool:
    text = error.message.lower()
    return any(
        phrase in text
        for phrase in ("unsupported keyless", "route unavailable", "not available to keyless")
    )


def classify_error(error: CmcClientError) -> CapabilityClassification:
    """Map client failures without turning ordinary HTTP policy errors into unsupported.

    A deterministic 4xx stays TRANSIENT_ERROR (capability unknown): PLAN.md 13.1
    requires a repeated run or explicit provider wording before UNSUPPORTED.
    """

    if error.code is ErrorCode.RATE_LIMITED:
        return CapabilityClassification.RATE_LIMITED
    if error.code in {
        ErrorCode.UPSTREAM_TIMEOUT,
        ErrorCode.UPSTREAM_NETWORK_ERROR,
        ErrorCode.UPSTREAM_5XX,
        ErrorCode.UPSTREAM_HTTP_ERROR,
    }:
        return CapabilityClassification.TRANSIENT_ERROR
    if error.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH:
        return CapabilityClassification.CONTRACT_MISMATCH
    if error.code is ErrorCode.UPSTREAM_APPLICATION_ERROR and _positive_unsupported(error):
        return CapabilityClassification.UNSUPPORTED
    return CapabilityClassification.TRANSIENT_ERROR


def _server_version() -> str:
    try:
        return version("coinmarketcap-keyless-mcp")
    except PackageNotFoundError:
        try:
            return subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"


async def verify_live(
    *,
    selected_tools: set[str] | None = None,
    client_factory: Callable[[], KeylessHttpClient] = lambda: KeylessHttpClient(
        cache_enabled=False, max_concurrency=1
    ),
) -> dict[str, Any]:
    """Run selected probes serially and return only concise evidence."""

    selected = [
        probe for probe in LIVE_MATRIX if selected_tools is None or probe.tool in selected_tools
    ]
    unknown = (selected_tools or set()) - {probe.tool for probe in LIVE_MATRIX}
    if unknown:
        raise ValueError("unknown tool(s): " + ", ".join(sorted(unknown)))
    routes: list[RouteEvidence] = []
    category_id: str | None = None
    async with client_factory() as client:
        for probe in selected:
            started = time.monotonic()
            try:
                params = await _probe_params(client, probe, category_id)
                payload = await client.get(probe.route, params)
                evidence = _shape_check(payload.get("data"), probe.shape)
                if probe.tool == "cmc_crypto_categories":
                    category_id = _first_category_id(payload.get("data"))
                routes.append(
                    RouteEvidence(
                        probe.tool,
                        probe.route,
                        "SUPPORTED",
                        getattr(client, "_last_status_code", 200),
                        0,
                        getattr(client, "_last_attempts", 1),
                        int((time.monotonic() - started) * 1000),
                        evidence,
                    )
                )
            except _PrerequisiteFailed as exc:
                routes.append(
                    RouteEvidence(
                        probe.tool,
                        probe.route,
                        exc.classification.value,
                        None,
                        None,
                        0,
                        int((time.monotonic() - started) * 1000),
                        exc.detail,
                    )
                )
            except ValueError as exc:
                routes.append(
                    RouteEvidence(
                        probe.tool,
                        probe.route,
                        "CONTRACT_MISMATCH",
                        200,
                        0,
                        1,
                        int((time.monotonic() - started) * 1000),
                        str(exc),
                    )
                )
            except CmcClientError as exc:
                routes.append(
                    RouteEvidence(
                        probe.tool,
                        probe.route,
                        classify_error(exc).value,
                        exc.status_code,
                        exc.provider_error_code,
                        exc.attempts,
                        int((time.monotonic() - started) * 1000),
                        exc.message,
                    )
                )
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "base_url": BASE_URL,
        "server_version": _server_version(),
        "routes": [asdict(route) for route in routes],
    }


def write_evidence(report: Mapping[str, Any], directory: Path = Path("verification")) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"live-capability-{stamp}.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Opt-in live CoinMarketCap keyless capability verification"
    )
    parser.add_argument(
        "--tool", action="append", dest="tools", help="rerun one or more tools only"
    )
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    report = await verify_live(selected_tools=set(args.tools) if args.tools else None)
    path = write_evidence(report)
    counts: dict[str, int] = {}
    for route in report["routes"]:
        counts[route["classification"]] = counts.get(route["classification"], 0) + 1
    print(f"Evidence written to {path}")
    print("Classification summary: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    return 0 if set(counts) <= {CapabilityClassification.SUPPORTED.value} else 1


def main(argv: list[str] | None = None) -> None:
    try:
        status = asyncio.run(_main_async(build_parser().parse_args(argv)))
    except (OSError, ValueError) as exc:
        print(f"live verification failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if status:
        raise SystemExit(status)


if __name__ == "__main__":
    main()

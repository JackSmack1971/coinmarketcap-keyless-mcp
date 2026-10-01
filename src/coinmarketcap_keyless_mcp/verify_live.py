"""Opt-in, serial live capability verification for the released v1 routes."""

from __future__ import annotations

import argparse
import asyncio
import json
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
    LiveProbe("cmc_crypto_map", {"symbol": "BTC"}, "mapping_or_nonempty_list"),
    LiveProbe("cmc_crypto_info", {"id": 1}, "nonempty_mapping"),
    LiveProbe("cmc_quotes_latest", {"id": "1,1027", "convert": "USD"}, "nonempty_list"),
    LiveProbe(
        "cmc_listings_latest",
        {"start": 1, "limit": 2, "convert": "USD"},
        "nonempty_list",
    ),
    LiveProbe("cmc_global_metrics_latest", {"convert": "USD"}, "nonempty_mapping"),
    LiveProbe("cmc_fear_greed_latest", {}, "nonempty_mapping"),
    LiveProbe("cmc_fear_greed_historical", {"start": 1, "limit": 2}, "nonempty_list"),
    LiveProbe("cmc_altcoin_season_latest", {}, "nonempty_mapping"),
    LiveProbe("cmc_altcoin_season_historical", {"timeframe": "7d"}, "history_mapping"),
    LiveProbe("cmc_cmc100_latest", {}, "index_latest"),
    LiveProbe("cmc_cmc100_historical", {"count": 2, "interval": "daily"}, "index_history"),
    LiveProbe("cmc_cmc20_latest", {}, "index_latest"),
    LiveProbe("cmc_cmc20_historical", {"count": 2, "interval": "daily"}, "index_history"),
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


def _shape_check(data: Any, shape: str) -> str:
    if shape == "mapping_or_nonempty_list" and (
        (isinstance(data, Mapping) and bool(data)) or (isinstance(data, list) and bool(data))
    ):
        return "response type=%s; minimum shape passed" % type(data).__name__
    if shape == "nonempty_mapping" and isinstance(data, Mapping) and bool(data):
        return "response type=mapping; required keys/data present"
    if shape == "nonempty_list" and isinstance(data, list) and bool(data):
        return "response type=list; result count=%d" % len(data)
    if shape == "history_mapping" and isinstance(data, Mapping) and isinstance(data.get("points"), list) and bool(data["points"]):
        return "history mapping with points; result count=%d" % len(data["points"])
    if shape == "index_latest" and isinstance(data, Mapping) and bool(data):
        return "response type=mapping; index structure present"
    if shape == "index_history" and (
        (isinstance(data, list) and bool(data))
        or (isinstance(data, Mapping) and bool(data.get("values")))
    ):
        count = len(data) if isinstance(data, list) else len(data["values"])
        return "index history structure present; result count=%d" % count
    raise ValueError("minimum endpoint shape did not pass")


def _positive_unsupported(error: CmcClientError) -> bool:
    text = error.message.lower()
    return any(phrase in text for phrase in ("unsupported keyless", "route unavailable", "not available to keyless"))


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

    selected = [probe for probe in LIVE_MATRIX if selected_tools is None or probe.tool in selected_tools]
    unknown = (selected_tools or set()) - {probe.tool for probe in LIVE_MATRIX}
    if unknown:
        raise ValueError("unknown tool(s): " + ", ".join(sorted(unknown)))
    routes: list[RouteEvidence] = []
    async with client_factory() as client:
        for probe in selected:
            started = time.monotonic()
            try:
                payload = await client.get(probe.route, probe.params)
                evidence = _shape_check(payload.get("data"), probe.shape)
                routes.append(RouteEvidence(probe.tool, probe.route, "SUPPORTED", getattr(client, "_last_status_code", 200), 0, getattr(client, "_last_attempts", 1), int((time.monotonic() - started) * 1000), evidence))
            except ValueError as exc:
                routes.append(RouteEvidence(probe.tool, probe.route, "CONTRACT_MISMATCH", 200, 0, 1, int((time.monotonic() - started) * 1000), str(exc)))
            except CmcClientError as exc:
                routes.append(RouteEvidence(probe.tool, probe.route, classify_error(exc).value, exc.status_code, exc.provider_error_code, exc.attempts, int((time.monotonic() - started) * 1000), exc.message))
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
    parser = argparse.ArgumentParser(description="Opt-in live CoinMarketCap keyless capability verification")
    parser.add_argument("--tool", action="append", dest="tools", help="rerun one or more tools only")
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

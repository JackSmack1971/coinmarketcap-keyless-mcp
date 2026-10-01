from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from coinmarketcap_keyless_mcp.client import KeylessHttpClient
from coinmarketcap_keyless_mcp.contracts import BASE_URL, ROUTES
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
from coinmarketcap_keyless_mcp.verify_live import (
    LIVE_MATRIX,
    CapabilityClassification,
    classify_error,
    verify_live,
    write_evidence,
)


def _envelope(data):
    return {"status": {"error_code": 0}, "data": data}


def test_matrix_contains_exactly_thirteen_routes_and_minimal_queries() -> None:
    assert [probe.tool for probe in LIVE_MATRIX] == list(ROUTES)
    assert LIVE_MATRIX[0].params == {"symbol": "BTC"}
    assert LIVE_MATRIX[2].params == {"id": "1,1027", "convert": "USD"}
    assert all(probe.route == ROUTES[probe.tool] for probe in LIVE_MATRIX)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ErrorCode.RATE_LIMITED, CapabilityClassification.RATE_LIMITED),
        (ErrorCode.UPSTREAM_TIMEOUT, CapabilityClassification.TRANSIENT_ERROR),
        (ErrorCode.UPSTREAM_NETWORK_ERROR, CapabilityClassification.TRANSIENT_ERROR),
        (ErrorCode.UPSTREAM_5XX, CapabilityClassification.TRANSIENT_ERROR),
        (ErrorCode.UPSTREAM_CONTRACT_MISMATCH, CapabilityClassification.CONTRACT_MISMATCH),
        (ErrorCode.UPSTREAM_HTTP_ERROR, CapabilityClassification.TRANSIENT_ERROR),
    ],
)
def test_error_classification(code, expected) -> None:
    assert classify_error(CmcClientError(code, "failure", status_code=404, attempts=3)) is expected


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_ordinary_http_policy_errors_require_more_evidence(status_code: int) -> None:
    assert classify_error(CmcClientError(ErrorCode.UPSTREAM_HTTP_ERROR, str(status_code), status_code=status_code)) is CapabilityClassification.TRANSIENT_ERROR
    assert classify_error(CmcClientError(ErrorCode.UPSTREAM_APPLICATION_ERROR, "route unavailable", details={"positive_unsupported": True})) is CapabilityClassification.UNSUPPORTED


@pytest.mark.asyncio
async def test_verification_is_serial_exact_route_get_and_no_auth() -> None:
    active = 0
    order: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active
        active += 1
        assert active == 1
        order.append(request.url.path)
        assert request.method == "GET"
        assert request.url.path.startswith("/public-api/")
        assert "x-cmc_pro_api_key" not in request.headers
        assert "authorization" not in request.headers
        active -= 1
        return httpx.Response(200, json=_envelope({"ok": True}))

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), cache_enabled=False, max_concurrency=1) as client:
        report = await verify_live(client_factory=lambda: client)
    assert len(report["routes"]) == 13
    assert [item["route"] for item in report["routes"]] == [probe.route for probe in LIVE_MATRIX]
    assert order == [f"/public-api{probe.route}" for probe in LIVE_MATRIX]


@pytest.mark.asyncio
async def test_supported_shape_and_contract_mismatch_are_distinguished() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_envelope({"ok": True}))

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), cache_enabled=False) as client:
        report = await verify_live(selected_tools={"cmc_global_metrics_latest"}, client_factory=lambda: client)
    assert report["routes"][0]["classification"] == "SUPPORTED"

    async with KeylessHttpClient(_transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": {"error_code": 0}, "data": []})), cache_enabled=False) as client:
        report = await verify_live(selected_tools={"cmc_global_metrics_latest"}, client_factory=lambda: client)
    assert report["routes"][0]["classification"] == "CONTRACT_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(429), "RATE_LIMITED"),
        (httpx.Response(503), "TRANSIENT_ERROR"),
        (httpx.ReadTimeout("timeout"), "TRANSIENT_ERROR"),
        (httpx.ConnectError("network"), "TRANSIENT_ERROR"),
        (httpx.Response(200, json={"status": {"error_code": 0}}), "CONTRACT_MISMATCH"),
    ],
)
async def test_failure_classifications(response, expected) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), cache_enabled=False, max_attempts=1) as client:
        report = await verify_live(selected_tools={"cmc_crypto_map"}, client_factory=lambda: client)
    assert report["routes"][0]["classification"] == expected


@pytest.mark.asyncio
async def test_selected_route_rerun_and_evidence_omit_payload(tmp_path: Path) -> None:
    async with KeylessHttpClient(_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_envelope({"price": 123}))), cache_enabled=False) as client:
        report = await verify_live(selected_tools={"cmc_crypto_info"}, client_factory=lambda: client)
    path = write_evidence(report, tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [route["tool"] for route in saved["routes"]] == ["cmc_crypto_info"]
    assert saved["base_url"] == BASE_URL
    assert "price" not in json.dumps(saved)

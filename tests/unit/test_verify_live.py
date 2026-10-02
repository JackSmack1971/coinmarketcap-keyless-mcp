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
    _shape_check,
    classify_error,
    verify_live,
    write_evidence,
)


def _envelope(data):
    return {"status": {"error_code": 0}, "data": data}


_ASSET = {"id": 1, "name": "Bitcoin", "symbol": "BTC", "slug": "bitcoin"}
_QUOTED = {**_ASSET, "quote": [{"id": 2781, "symbol": "USD", "price": 63120.95}]}
_CONSTITUENTS = [{"id": 1, "name": "Bitcoin", "symbol": "BTC", "weight": 0.5}]

# Minimal documented shapes for each route (CoinMarketCap pro-api-reference schemas).
VALID_DATA = {
    "cmc_crypto_map": [_ASSET],
    "cmc_crypto_info": {"1": _ASSET},
    "cmc_quotes_latest": [_QUOTED, {**_QUOTED, "id": 1027, "symbol": "ETH"}],
    "cmc_listings_latest": [_QUOTED],
    "cmc_global_metrics_latest": {
        "btc_dominance": 57.1,
        "quote": {"USD": {"total_market_cap": 2.4e12, "total_volume_24h": 9.1e10}},
    },
    "cmc_fear_greed_latest": {"value": 40, "value_classification": "Neutral"},
    "cmc_fear_greed_historical": [
        {"timestamp": "1726617600", "value": 38, "value_classification": "Fear"}
    ],
    "cmc_altcoin_season_latest": {"altcoin_index": 31, "snapshot_time": "2026-10-01"},
    "cmc_altcoin_season_historical": {"points": [{"altcoin_index": 31, "timestamp": "t"}]},
    "cmc_cmc100_latest": {"value": 212.4, "constituents": _CONSTITUENTS},
    "cmc_cmc100_historical": [{"value": 210.1, "update_time": "t", "constituents": []}],
    "cmc_cmc20_latest": {"value": 160.2, "constituents": _CONSTITUENTS},
    "cmc_cmc20_historical": {"values": [{"value": 158.3, "update_time": "t"}]},
    "cmc_simple_price": [{"id": 1, "quotes": [{"symbol": "USD", "price": 63120.95}]}],
    "cmc_crypto_categories": [{"id": "605e2ce9d41eae1066535f7c", "name": "A16Z Portfolio"}],
    "cmc_crypto_category": {"1": {"id": "605e2ce9d41eae1066535f7c", "coins": [_QUOTED]}},
    "cmc_price_conversion": {"amount": 1, "quote": {"USD": {"price": 63120.95}}},
    "cmc_exchange_map": [{"id": 270, "slug": "binance", "name": "Binance"}],
    "cmc_dex_platform_list": [
        {"id": 1, "n": "Ethereum", "pltA": "ETH"},
        {"id": 2, "n": "B² Network"},  # pltA may be absent
    ],
    "cmc_dex_token_price": {"p": 0.9998, "pid": 1, "a": "0xA0b86991"},
    # Only a non-empty string addr is required; n/sym/plt and market fields are optional
    # and addr need not equal the requested address (case may differ).
    "cmc_dex_token": {"addr": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"},
}

UNRELATED = {"ok": True}
# Each entry must fail its route's minimum shape although it is a non-empty container.
INVALID_DATA = {
    "cmc_crypto_map": [UNRELATED, [1], "BTC", [{"id": "1"}], [{"id": True}], {"1": _ASSET}],
    "cmc_crypto_info": [UNRELATED, {"1": UNRELATED}, {"1": []}, {"1": [UNRELATED]}, [_ASSET]],
    "cmc_quotes_latest": [[UNRELATED], [_ASSET], [{**_ASSET, "quote": []}], ["BTC"], UNRELATED],
    "cmc_listings_latest": [[UNRELATED], [_ASSET], [{**_ASSET, "quote": "USD"}], [1, 2]],
    "cmc_global_metrics_latest": [
        UNRELATED,
        {"quote": {}},
        {"quote": {"USD": UNRELATED}},
        {"quote": {"USD": {"total_market_cap": "2.4e12"}}},
        {"quote": {"USD": {"total_market_cap": True}}},
        {"quote": {"USD": {"total_market_cap": float("nan")}}},
        [UNRELATED],
    ],
    "cmc_fear_greed_latest": [
        UNRELATED,
        {"value": "40", "value_classification": "Neutral"},
        {"value": 40},
        {"value": 40, "value_classification": 1},
    ],
    "cmc_fear_greed_historical": [[UNRELATED], [{"value": "38"}], [38], UNRELATED],
    "cmc_altcoin_season_latest": [UNRELATED, {"altcoin_index": "31"}, {"altcoin_index": None}],
    "cmc_altcoin_season_historical": [
        UNRELATED,
        {"points": []},
        {"points": [1, 2]},
        {"points": [{}]},
        {"points": "x"},
    ],
    "cmc_cmc100_latest": [
        UNRELATED,
        {"value": 1.0},
        {"value": 1.0, "constituents": []},
        {"value": 1.0, "constituents": [UNRELATED]},
        {"value": "1.0", "constituents": _CONSTITUENTS},
    ],
    "cmc_cmc100_historical": [
        {"values": "x"},
        {"values": ["1.0"]},
        [UNRELATED],
        [1.0],
        {"values": []},
        UNRELATED,
    ],
    "cmc_cmc20_latest": [UNRELATED, {"constituents": _CONSTITUENTS}],
    "cmc_cmc20_historical": [[{"value": "1"}], {"values": [UNRELATED]}, UNRELATED],
    "cmc_simple_price": [
        [],
        UNRELATED,
        [{"id": True, "quotes": [{"price": 1.0}]}],
        [{"id": 0, "quotes": [{"price": 1.0}]}],
        [{"id": "1", "quotes": [{"price": 1.0}]}],
        [{"id": 1, "quotes": []}],
        [{"id": 1}],
        [{"id": 1, "quotes": {"USD": {"price": 1.0}}}],
        [{"id": 1, "quotes": [{"price": True}]}],
        [{"id": 1, "quotes": [{"price": float("nan")}]}],
        [{"id": 1, "quotes": [{"price": "1.0"}]}],
    ],
    "cmc_crypto_categories": [
        [],
        UNRELATED,
        [{"id": "", "name": "x"}],
        [{"id": 1, "name": "x"}],
        [{"id": "a"}],
        [{"id": "a", "name": ""}],
    ],
    "cmc_crypto_category": [
        {},
        [],
        {"1": "category"},
        {"1": []},
        {"1": {"coins": []}},
        {"1": {"id": "", "coins": []}},
        {"1": {"id": 605, "coins": []}},
        {"1": {"id": "605e", "coins": {}}},
        {"1": {"id": "605e"}},
        {"id": "605e", "coins": []},
    ],
    "cmc_price_conversion": [
        UNRELATED,
        [],
        {"amount": True, "quote": {"USD": {"price": 1.0}}},
        {"amount": float("nan"), "quote": {"USD": {"price": 1.0}}},
        {"amount": "1", "quote": {"USD": {"price": 1.0}}},
        {"amount": 1, "quote": {}},
        {"amount": 1, "quote": {"USD": {"price": True}}},
        {"amount": 1, "quote": {"USD": UNRELATED}},
        {"amount": 1},
    ],
    "cmc_dex_platform_list": [
        [],
        UNRELATED,
        ["Ethereum"],
        [{"n": "Ethereum"}],
        [{"id": True, "n": "Ethereum"}],
        [{"id": "1", "n": "Ethereum"}],
        [{"id": 1.0, "n": "Ethereum"}],
        [{"id": 1}],
        [{"id": 1, "n": ""}],
        [{"id": 1, "n": 5}],
        [{"id": 1, "n": "Ethereum"}, {"id": 2}],
    ],
    "cmc_dex_token": [
        {},
        [],
        [{"addr": "0xA0b8"}],
        "0xA0b8",
        {"n": "USD Coin", "sym": "USDC", "plt": "Ethereum", "p": "1.0"},
        {"addr": ""},
        {"addr": None},
        {"addr": 1},
        {"addr": ["0xA0b8"]},
        {"addr": {"v": "0xA0b8"}},
    ],
    "cmc_dex_token_price": [
        {},
        [],
        [{"p": 1.0}],
        {"pid": 1},
        {"p": True},
        {"p": "1.0"},
        {"p": None},
        {"p": float("nan")},
        {"p": float("inf")},
    ],
    "cmc_exchange_map": [
        [],
        UNRELATED,
        [{"id": True, "slug": "binance"}],
        [{"id": 0, "slug": "binance"}],
        [{"id": "270", "slug": "binance"}],
        [{"id": 270, "slug": ""}],
        [{"id": 270}],
    ],
}


def _probe(tool: str):
    return next(probe for probe in LIVE_MATRIX if probe.tool == tool)


def test_every_route_has_valid_and_invalid_shape_fixtures() -> None:
    assert set(VALID_DATA) == set(ROUTES) == set(INVALID_DATA)


@pytest.mark.parametrize("tool", list(ROUTES))
def test_documented_minimum_shapes_pass(tool: str) -> None:
    assert _shape_check(VALID_DATA[tool], _probe(tool).shape)


@pytest.mark.parametrize(
    ("tool", "data"), [(tool, data) for tool, cases in INVALID_DATA.items() for data in cases]
)
def test_unrelated_or_mistyped_data_fails_minimum_shape(tool: str, data) -> None:
    with pytest.raises(ValueError, match="minimum endpoint shape did not pass"):
        _shape_check(data, _probe(tool).shape)


def test_matrix_contains_exactly_twenty_routes_and_minimal_queries() -> None:
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
    assert (
        classify_error(
            CmcClientError(ErrorCode.UPSTREAM_HTTP_ERROR, str(status_code), status_code=status_code)
        )
        is CapabilityClassification.TRANSIENT_ERROR
    )
    assert (
        classify_error(
            CmcClientError(
                ErrorCode.UPSTREAM_APPLICATION_ERROR,
                "route unavailable",
                details={"positive_unsupported": True},
            )
        )
        is CapabilityClassification.UNSUPPORTED
    )


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
        if request.url.path.endswith(ROUTES["cmc_crypto_categories"]):
            return httpx.Response(200, json=_envelope(VALID_DATA["cmc_crypto_categories"]))
        return httpx.Response(200, json=_envelope({"ok": True}))

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False, max_concurrency=1
    ) as client:
        report = await verify_live(client_factory=lambda: client)
    assert len(report["routes"]) == 21
    assert [item["route"] for item in report["routes"]] == [probe.route for probe in LIVE_MATRIX]
    assert order == [f"/public-api{probe.route}" for probe in LIVE_MATRIX]


@pytest.mark.asyncio
async def test_supported_shape_and_contract_mismatch_are_distinguished() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_envelope(VALID_DATA["cmc_global_metrics_latest"]))

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_global_metrics_latest"}, client_factory=lambda: client
        )
    assert report["routes"][0]["classification"] == "SUPPORTED"

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": {"error_code": 0}, "data": []})
        ),
        cache_enabled=False,
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_global_metrics_latest"}, client_factory=lambda: client
        )
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

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False, max_attempts=1
    ) as client:
        report = await verify_live(selected_tools={"cmc_crypto_map"}, client_factory=lambda: client)
    assert report["routes"][0]["classification"] == expected


@pytest.mark.asyncio
async def test_selected_route_rerun_and_evidence_omit_payload(tmp_path: Path) -> None:
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_envelope({"price": 123}))
        ),
        cache_enabled=False,
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_info"}, client_factory=lambda: client
        )
    path = write_evidence(report, tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [route["tool"] for route in saved["routes"]] == ["cmc_crypto_info"]
    assert saved["base_url"] == BASE_URL
    assert "price" not in json.dumps(saved)


@pytest.mark.parametrize(
    ("classifications", "expected"), [(["SUPPORTED"], 0), (["SUPPORTED", "RATE_LIMITED"], 1)]
)
def test_main_exit_code_reflects_classifications(monkeypatch, tmp_path, classifications, expected):
    from coinmarketcap_keyless_mcp import verify_live as module

    async def fake_verify_live(selected_tools=None):
        return {"routes": [{"classification": c} for c in classifications]}

    monkeypatch.setattr(module, "verify_live", fake_verify_live)
    monkeypatch.setattr(module, "write_evidence", lambda report: tmp_path / "e.json")
    if expected:
        with pytest.raises(SystemExit) as exc:
            module.main([])
        assert exc.value.code == expected
    else:
        module.main([])


def test_category_results_map_fixtures_required_by_contract() -> None:
    shape = _probe("cmc_crypto_category").shape
    category = {"id": "605e2ce9d41eae1066535f7c", "coins": [_QUOTED]}
    assert _shape_check({"1": category}, shape)
    assert _shape_check({"1": {**category, "coins": []}}, shape)  # empty coins accepted
    assert _shape_check({"any-provider-key": category}, shape)  # outer keys not interpreted
    for rejected in (
        {},  # empty outer map
        {"1": "not-a-mapping"},
        {"1": {"coins": []}},  # missing id
        {"1": {"id": "", "coins": []}},
        {"1": {"id": 1, "coins": []}},
        {"1": {"id": "605e", "coins": "x"}},  # non-list coins
        category,  # data is not itself the category object (C2)
    ):
        with pytest.raises(ValueError, match="minimum endpoint shape did not pass"):
            _shape_check(rejected, shape)


@pytest.mark.asyncio
async def test_category_probe_reuses_category_id_from_categories_probe() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith(ROUTES["cmc_crypto_categories"]):
            return httpx.Response(200, json=_envelope(VALID_DATA["cmc_crypto_categories"]))
        return httpx.Response(200, json=_envelope(VALID_DATA["cmc_crypto_category"]))

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_categories", "cmc_crypto_category"},
            client_factory=lambda: client,
        )
    assert [route["classification"] for route in report["routes"]] == ["SUPPORTED", "SUPPORTED"]
    assert seen == [
        ("/public-api/v1/cryptocurrency/categories", {"start": "1", "limit": "1"}),
        (
            "/public-api/v1/cryptocurrency/category",
            {"id": "605e2ce9d41eae1066535f7c", "start": "1", "limit": "1", "convert": "USD"},
        ),
    ]


@pytest.mark.asyncio
async def test_category_probe_alone_looks_up_one_category_id_first() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith(ROUTES["cmc_crypto_categories"]):
            return httpx.Response(200, json=_envelope(VALID_DATA["cmc_crypto_categories"]))
        assert request.url.params["id"] == "605e2ce9d41eae1066535f7c"
        return httpx.Response(200, json=_envelope(VALID_DATA["cmc_crypto_category"]))

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_category"}, client_factory=lambda: client
        )
    assert report["routes"][0]["classification"] == "SUPPORTED"
    assert paths == [
        "/public-api/v1/cryptocurrency/categories",
        "/public-api/v1/cryptocurrency/category",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("categories", [[], [{"id": ""}], [{"id": 5}], ["x"], {"id": "a"}])
async def test_category_probe_without_a_category_id_is_not_a_category_mismatch(categories) -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_envelope(categories))

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_category"}, client_factory=lambda: client
        )
    route = report["routes"][0]
    assert route["classification"] == "TRANSIENT_ERROR"
    assert (route["http_status"], route["cmc_error_code"], route["attempts"]) == (None, None, 0)
    assert route["evidence"] == (
        "category id lookup on /v1/cryptocurrency/categories returned no category id; "
        "/v1/cryptocurrency/category was not called"
    )
    assert paths == ["/public-api/v1/cryptocurrency/categories"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "classification", "code"),
    [
        (httpx.Response(429), "RATE_LIMITED", "RATE_LIMITED"),
        (httpx.Response(503), "TRANSIENT_ERROR", "UPSTREAM_5XX"),
        (
            httpx.Response(
                200,
                json={
                    "status": {"error_code": 1, "error_message": "route unavailable"},
                    "data": None,
                },
            ),
            "TRANSIENT_ERROR",
            "UPSTREAM_APPLICATION_ERROR",
        ),
    ],
)
async def test_category_lookup_failure_is_attributed_to_the_lookup_not_the_category_route(
    response, classification, code
) -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return response

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False, max_attempts=1
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_category"}, client_factory=lambda: client
        )
    route = report["routes"][0]
    assert route["classification"] == classification
    assert (route["http_status"], route["cmc_error_code"], route["attempts"]) == (None, None, 0)
    assert route["evidence"] == (
        f"category id lookup on /v1/cryptocurrency/categories failed ({code}); "
        "/v1/cryptocurrency/category was not called"
    )
    assert paths == ["/public-api/v1/cryptocurrency/categories"]


def test_e1r_probes_use_minimal_contract_queries() -> None:
    assert _probe("cmc_simple_price").params == {"id": "1", "convert": "USD"}
    assert _probe("cmc_crypto_categories").params == {"start": 1, "limit": 1}
    assert _probe("cmc_crypto_category").params == {"start": 1, "limit": 1, "convert": "USD"}
    assert _probe("cmc_price_conversion").params == {"amount": "1", "id": 1, "convert": "USD"}
    assert _probe("cmc_exchange_map").params == {"start": 1, "limit": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed",
    [
        {"data": []},  # no status
        {"status": {"error_code": 0}},  # no data
        {"status": {"error_code": None}, "data": []},
    ],
)
async def test_lookup_contract_mismatch_is_not_an_s3_contract_mismatch(malformed) -> None:
    """D1: a malformed categories lookup must not be reported as an S3 contract mismatch."""

    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=malformed)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False, max_attempts=1
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_category"}, client_factory=lambda: client
        )
    route = report["routes"][0]
    assert paths == ["/public-api/v1/cryptocurrency/categories"]
    assert "/public-api/v1/cryptocurrency/category" not in paths
    assert route["tool"] == "cmc_crypto_category"
    assert route["classification"] == "TRANSIENT_ERROR"
    assert route["classification"] != "CONTRACT_MISMATCH"
    assert (route["http_status"], route["cmc_error_code"], route["attempts"]) == (None, None, 0)
    assert route["evidence"] == (
        "category id lookup on /v1/cryptocurrency/categories failed "
        "(UPSTREAM_CONTRACT_MISMATCH); /v1/cryptocurrency/category was not called"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "s3_data",
    [
        {"id": "605e2ce9d41eae1066535f7c", "coins": []},  # category object as data (C2)
        {},
        {"1": {"id": "605e", "coins": "x"}},
    ],
)
async def test_actual_s3_shape_failure_is_still_s3_contract_mismatch(s3_data) -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith(ROUTES["cmc_crypto_categories"]):
            return httpx.Response(200, json=_envelope(VALID_DATA["cmc_crypto_categories"]))
        return httpx.Response(200, json=_envelope(s3_data))

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), cache_enabled=False
    ) as client:
        report = await verify_live(
            selected_tools={"cmc_crypto_category"}, client_factory=lambda: client
        )
    assert paths == [
        "/public-api/v1/cryptocurrency/categories",
        "/public-api/v1/cryptocurrency/category",
    ]
    assert report["routes"][0]["classification"] == "CONTRACT_MISMATCH"
    assert report["routes"][0]["evidence"] == "minimum endpoint shape did not pass"


def test_e2a_probes_use_the_contract_fixture() -> None:
    assert _probe("cmc_dex_platform_list").params == {}
    assert _probe("cmc_dex_token_price").params == {
        "platform": "Ethereum",
        "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    }


def test_e2b_probe_uses_the_contract_fixture_and_minimum_shape() -> None:
    probe = _probe("cmc_dex_token")
    assert probe.route == "/v1/dex/token"
    assert probe.params == {
        "platform": "Ethereum",
        "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    }
    assert [p.tool for p in LIVE_MATRIX].count("cmc_dex_token") == 1

from __future__ import annotations

from datetime import UTC

import coinmarketcap_keyless_mcp.models as models


def test_naive_iso_timestamps_are_assigned_utc_independent_of_host_timezone(monkeypatch) -> None:
    class ParsedNaiveTimestamp:
        tzinfo = None

        def replace(self, *, tzinfo):
            self.assigned_timezone = tzinfo
            return self

        def timestamp(self) -> float:
            assert self.assigned_timezone is UTC
            return 123.0

    class Parser:
        @staticmethod
        def fromisoformat(value: str) -> ParsedNaiveTimestamp:
            return ParsedNaiveTimestamp()

    monkeypatch.setattr(models, "datetime", Parser)
    assert models.validate_time("2025-01-01T00:00:00", "time_start") == 123.0


import pytest  # noqa: E402


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (
            lambda: models.require_exactly_one_selector(ids=[], slugs=[]),
            "exactly one of ids, slugs, or symbols must be supplied",
        ),
        (
            lambda: models.require_exactly_one_selector(ids=[1, 1]),
            "ids must not contain duplicate values",
        ),
        (
            lambda: models.require_unique(["a", "a"], "convert"),
            "convert must not contain duplicate values",
        ),
        (lambda: models.validate_time("", "time_start"), "time_start must not be empty"),
        (
            lambda: models.validate_time("soon", "time_end"),
            "time_end must be a Unix timestamp or ISO-8601 timestamp",
        ),
        (lambda: models.validate_time("nan", "time_start"), "time_start must be finite"),
        (
            lambda: models.validate_time_bounds("x", None),
            "time_start must be a Unix timestamp or ISO-8601 timestamp",
        ),
        (
            lambda: models.validate_time_bounds(None, "x"),
            "time_end must be a Unix timestamp or ISO-8601 timestamp",
        ),
        (
            lambda: models.validate_time_bounds("2", "1"),
            "time_start must be less than or equal to time_end",
        ),
    ],
)
def test_validation_messages_are_exact(call, message: str) -> None:
    with pytest.raises(ValueError) as caught:
        call()
    assert str(caught.value) == message


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (1e-8, "0.00000001"),
        (1e12, "1000000000000"),
        (1.0, "1"),
        (5, "5"),
        (2.5, "2.5"),
        (0.1, "0.1"),
        (100.0, "100"),
        (123456.789, "123456.789"),
        (1.5e-7, "0.00000015"),
        (12345678901.25, "12345678901.25"),
    ],
)
def test_plain_decimal_never_uses_exponent_notation(amount: float, expected: str) -> None:
    assert models.plain_decimal(amount) == expected


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ((1.0, 1, None, None, None), {"amount": "1", "id": 1, "convert": "USD"}),
        ((1.0, None, "btc", None, None), {"amount": "1", "symbol": "btc", "convert": "USD"}),
        ((2.0, 1, None, "EUR", None), {"amount": "2", "id": 1, "convert": "EUR"}),
        ((2.0, None, "BTC", None, 2781), {"amount": "2", "symbol": "BTC", "convert_id": 2781}),
    ],
)
def test_price_conversion_params_build_exact_query(arguments, expected) -> None:
    result = models.price_conversion_params(*arguments)
    assert result == expected
    assert list(result) == list(expected)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ((1.0, None, None, None, None), "exactly one of id or symbol must be supplied"),
        ((1.0, 1, "BTC", None, None), "exactly one of id or symbol must be supplied"),
        ((1.0, 1, None, "USD", 2781), "at most one of convert or convert_id may be supplied"),
    ],
)
def test_price_conversion_params_reject_invalid_source_and_target(arguments, message) -> None:
    with pytest.raises(ValueError) as caught:
        models.price_conversion_params(*arguments)
    assert str(caught.value) == message


def test_e1r_type_bounds() -> None:
    from pydantic import TypeAdapter, ValidationError

    amount = TypeAdapter(models.ConversionAmount)
    assert amount.validate_python(1e-8) == 1e-8
    assert amount.validate_python(1e12) == 1e12
    assert amount.validate_python(7) == 7.0
    for rejected in (True, "1", 0, 9.9e-9, 1.0000001e12, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            amount.validate_python(rejected)

    positive = TypeAdapter(models.StrictPositiveInt)
    assert positive.validate_python(1) == 1
    for rejected in (True, False, 0, "1", 1.0):
        with pytest.raises(ValidationError):
            positive.validate_python(rejected)

    category = TypeAdapter(models.CategoryId)
    assert category.validate_python("605e2CE9") == "605e2CE9"
    assert category.validate_python("A" * 64) == "A" * 64
    for rejected in ("", "A" * 65, "a-b", "a b", "a\n", "a,b", "a&b=c", "é"):
        with pytest.raises(ValidationError):
            category.validate_python(rejected)


def test_ids_items_are_strict_positive_integers() -> None:
    from pydantic import TypeAdapter, ValidationError

    ids = TypeAdapter(models.Ids)
    assert ids.validate_python([1, 1027]) == [1, 1027]
    for rejected in ([True], [False], [1, True], ["1"], [1.0], [0], []):
        with pytest.raises(ValidationError):
            ids.validate_python(rejected)
    assert ids.json_schema()["items"] == {"minimum": 1, "type": "integer"}


def test_e2a_dex_platform_and_address_types() -> None:
    from pydantic import TypeAdapter, ValidationError

    platform = TypeAdapter(models.DexPlatform)
    for accepted in ("Ethereum", "ethereum", "E", "B² Network", "Arbitrum One", "x" * 64):
        assert platform.validate_python(accepted) == accepted
    for rejected in (
        "",
        "x" * 65,
        " E",
        "E ",
        " E",
        "E\n",
        "E\r",
        "E\x1fx",
        "E\x7fx",
        "E\x9fx",
        "a&b",
        "a=b",
        "a?b",
        "a#b",
    ):
        with pytest.raises(ValidationError):
            platform.validate_python(rejected)

    address = TypeAdapter(models.DexAddress)
    for accepted in ("0xA0b8", "a", "a" * 128, "So1:_.-Z"):
        assert address.validate_python(accepted) == accepted
    for rejected in ("", "a" * 129, "0x 1", "0x\n", "0x/1", "0x&1", "0x%1", "0x,1", "é"):
        with pytest.raises(ValidationError):
            address.validate_python(rejected)


@pytest.mark.parametrize(
    ("platform", "address"),
    [
        ("Ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
        ("eThErEuM", "0xa0B86991C6218B36"),
        ("B² Network", "So1:_.-Z"),
        ("BNB Smart Chain (BEP20)", "a"),
    ],
)
def test_dex_token_price_params_is_exactly_platform_then_address(
    platform: str, address: str
) -> None:
    params = models.dex_token_price_params(platform, address)
    assert params == {"platform": platform, "address": address}
    assert list(params) == ["platform", "address"]
    assert len(params) == 2
    assert params["platform"] is platform  # passed through, never normalized
    assert params["address"] is address


def test_dex_token_price_params_does_not_swap_or_default_values() -> None:
    params = models.dex_token_price_params("P", "A")
    assert params == {"platform": "P", "address": "A"}
    assert "convert" not in params and "network" not in params


@pytest.mark.parametrize(
    ("platform", "address"),
    [
        ("Ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
        ("eThErEuM", "0xa0B86991C6218B36"),
        ("B² Network", "So1:_.-Z"),
        ("BNB Smart Chain (BEP20)", "a"),
    ],
)
def test_dex_token_params_is_exactly_platform_then_address(platform: str, address: str) -> None:
    params = models.dex_token_params(platform, address)
    assert params == {"platform": platform, "address": address}
    assert list(params) == ["platform", "address"]
    assert len(params) == 2
    assert params["platform"] is platform  # passed through, never normalized
    assert params["address"] is address


def test_dex_token_params_does_not_swap_or_default_values() -> None:
    params = models.dex_token_params("P", "A")
    assert params == {"platform": "P", "address": "A"}
    assert "network_slug" not in params and "contract_address" not in params


@pytest.mark.parametrize("platform", ["Ethereum", "eThErEuM", "B² Network", "x" * 64, "1"])
def test_dex_platform_detail_params_is_exactly_platform_name(platform: str) -> None:
    params = models.dex_platform_detail_params(platform)
    assert params == {"platformName": platform}
    assert list(params) == ["platformName"]
    assert params["platformName"] is platform  # passed through, never normalized
    assert "platform" not in params and "platform_name" not in params

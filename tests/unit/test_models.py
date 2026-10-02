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

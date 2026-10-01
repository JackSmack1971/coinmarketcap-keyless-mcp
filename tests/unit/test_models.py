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

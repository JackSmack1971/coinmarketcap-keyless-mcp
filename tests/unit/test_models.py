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

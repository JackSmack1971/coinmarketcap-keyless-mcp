"""Stable internal error classifications for the upstream client."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_NETWORK_ERROR = "UPSTREAM_NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    UPSTREAM_HTTP_ERROR = "UPSTREAM_HTTP_ERROR"
    UPSTREAM_APPLICATION_ERROR = "UPSTREAM_APPLICATION_ERROR"
    UPSTREAM_CONTRACT_MISMATCH = "UPSTREAM_CONTRACT_MISMATCH"
    UNSUPPORTED_ROUTE = "UNSUPPORTED_ROUTE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class CmcClientError(Exception):
    """An expected failure at the client/provider boundary."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        attempts: int = 1,
        provider_error_code: int | str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.attempts = attempts
        self.provider_error_code = provider_error_code
        self.details = details

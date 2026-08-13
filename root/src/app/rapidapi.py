from __future__ import annotations

from logging import Logger
from typing import Protocol

from flask import Request


class ApiAccessError(RuntimeError):
    """A future API access policy can raise this for a stable API error."""

    def __init__(self, code: str, message: str, status_code: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ApiAccessPolicy(Protocol):
    """Authorization and rate-limit seam for a future RapidAPI deployment."""

    def authorize(self, request: Request) -> None:
        """Authorize a request or raise ApiAccessError."""


class AllowAllApiAccessPolicy:
    """Local/default policy; the hosting gateway may enforce API keys and limits."""

    def authorize(self, request: Request) -> None:
        return None


class ApiUsageLogger(Protocol):
    def record(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
    ) -> None:
        """Record non-sensitive API request usage metadata."""


class LoggingApiUsageLogger:
    """Write request usage to the application logger without query or auth data."""

    def __init__(self, logger: Logger):
        self._logger = logger

    def record(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
    ) -> None:
        self._logger.info(
            "api_request",
            extra={
                "api_usage": {
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                }
            },
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class QuotaInfo:
    remaining: int | None = None
    used: int | None = None
    last_cost: int | None = None

    @classmethod
    def from_headers(cls, headers: dict[str, str] | None) -> "QuotaInfo":
        values = {key.lower(): value for key, value in (headers or {}).items()}

        def integer(name: str) -> int | None:
            try:
                return int(values[name]) if name in values else None
            except (TypeError, ValueError):
                return None

        return cls(
            remaining=integer("x-requests-remaining"),
            used=integer("x-requests-used"),
            last_cost=integer("x-requests-last"),
        )

    def as_message(self) -> str:
        parts = []
        if self.remaining is not None:
            parts.append(f"remaining {self.remaining}")
        if self.last_cost is not None:
            parts.append(f"last request cost {self.last_cost}")
        if self.used is not None:
            parts.append(f"used {self.used}")
        return ", ".join(parts)


class OddsProviderError(RuntimeError):
    """Base error for provider configuration, transport, and response failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        headers: dict[str, str] | None = None,
        quota: QuotaInfo | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.headers = headers or {}
        self.quota = quota


class OddsProviderAuthenticationError(OddsProviderError):
    """The provider rejected or the application lacks an API key."""


class OddsProviderQuotaExceeded(OddsProviderError):
    """The provider rejected a request because of rate or usage limits."""


class OddsProviderNotFound(OddsProviderError):
    """The requested provider event does not exist or is no longer available."""


class OddsProviderUnavailable(OddsProviderError):
    """The provider could not be reached or returned a server-side failure."""


class OddsProviderResponseError(OddsProviderError):
    """The provider returned a response that cannot be normalized safely."""


@dataclass(frozen=True)
class OddsOutcome:
    fighter: str
    moneyline: int


@dataclass(frozen=True)
class BookmakerOdds:
    key: str
    title: str
    last_update: str | None
    outcomes: tuple[OddsOutcome, ...]


@dataclass(frozen=True)
class OddsEvent:
    provider_event_id: str
    sport_key: str
    sport_title: str
    commence_time: str
    home_team: str
    away_team: str
    bookmakers: tuple[BookmakerOdds, ...] = ()


class OddsProvider(Protocol):
    last_quota: QuotaInfo | None

    def discover_events(
        self, event_ids: Sequence[str] | None = None
    ) -> list[OddsEvent]:
        ...

    def fetch_odds(self, event_ids: Sequence[str]) -> list[OddsEvent]:
        ...

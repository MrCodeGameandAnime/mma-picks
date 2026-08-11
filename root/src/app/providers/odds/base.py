from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class OddsProviderError(RuntimeError):
    """Base error for provider configuration, transport, and response failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.headers = headers or {}


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


@dataclass(frozen=True)
class OddsResult:
    provider_event_id: str
    status: str
    winner: str | None


class OddsProvider(Protocol):
    def upcoming_events(self) -> list[OddsEvent]:
        ...

    def get_event(self, event_id: str) -> OddsEvent:
        ...

    def get_odds(self, event_id: str) -> OddsEvent:
        ...

    def get_results(self, event_id: str) -> OddsResult:
        ...

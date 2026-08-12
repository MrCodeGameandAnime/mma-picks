from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PicksProviderError(RuntimeError):
    """Base error for analyst-picks provider failures."""


class PicksProviderUnavailable(PicksProviderError):
    """The configured source is unavailable or not suitable for ingestion."""


class PicksProviderResponseError(PicksProviderError):
    """A source response cannot be normalized into picks."""


@dataclass(frozen=True)
class NormalizedPick:
    """A source pick normalized before it reaches tracker persistence."""

    fighter_a: str
    fighter_b: str
    picked_fighter: str
    confidence: int
    source_identifier: str
    source_url: str
    published_at: str
    predicted_method: str | None = None
    external_provider: str | None = None
    external_fight_id: str | None = None


class PicksProvider(Protocol):
    name: str

    def fetch_picks(
        self,
        analyst_slug: str,
        *,
        event_name: str | None = None,
        event_date: str | None = None,
    ) -> list[NormalizedPick]:
        """Return normalized picks with source provenance."""


class UnsupportedPicksProvider:
    """Explicit placeholder until a permitted structured source is available."""

    name = "unsupported"

    def fetch_picks(
        self,
        analyst_slug: str,
        *,
        event_name: str | None = None,
        event_date: str | None = None,
    ) -> list[NormalizedPick]:
        raise PicksProviderUnavailable(
            "no reliable structured public picks source is configured; use manual entry"
        )
